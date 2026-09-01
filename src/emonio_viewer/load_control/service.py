from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from queue import Full, Queue
import time
import uuid
from typing import Any

from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEvent, RuntimeEventBus

from .config_store import LoadControlConfigStore
from .discovery import MockActuatorDiscovery
from .evidence import ControlEvidenceWriter, EvidenceWriteError
from .model import (
    ActuatorDescriptor,
    ControlMode,
    LoadControlTiming,
    PersistentLoadControlConfig,
    SafeState,
    SessionState,
    ThreePhasePower,
)
from .session import MockAckMode, MockActuatorSession
from .supervisor import EnableRejected, LoadControlSupervisor, SupervisorDecision


MOCK_ACTUATOR = ActuatorDescriptor(
    node_id="ARI-LOAD-MOCK-001",
    location="mock://ari-load-001",
    device_class="ARI_LOAD_ACTUATOR_MOCK",
    capabilities=("ACTIVE_LOAD_CONTROL",),
    p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
)


class LoadControlCommandError(RuntimeError):
    """Raised when an operator load-control command is not admissible."""


class LoadControlService:
    """Stage-1 owner for deterministic Viewer-side load-control supervision.

    This service contains no network actuator implementation. It uses only
    MockActuatorDiscovery and MockActuatorSession.
    """

    def __init__(
        self,
        bus: RuntimeEventBus,
        *,
        config_path: Path,
        evidence_path: Path,
        discovery: MockActuatorDiscovery | None = None,
        viewer_session_id: str | None = None,
        mock_boot_id: str = "MOCK-BOOT-001",
    ) -> None:
        self._bus = bus
        self._config_store = LoadControlConfigStore(config_path)
        self._evidence = ControlEvidenceWriter(evidence_path)
        self._discovery = discovery or MockActuatorDiscovery((MOCK_ACTUATOR,))
        self._viewer_session_id = viewer_session_id or uuid.uuid4().hex
        self._mock_boot_id = mock_boot_id
        self._config = self._config_store.load()
        self._timing: LoadControlTiming | None = None
        self._supervisor: LoadControlSupervisor | None = None
        self._session: MockActuatorSession | None = None
        self._hello = None
        self._visible: tuple[ActuatorDescriptor, ...] = ()
        self._latest_samples: dict[str, MeasurementSample] = {}
        self._subscriber: Queue[RuntimeEvent] | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_sentinel = object()
        self._started = False
        self._last_service_error: str | None = None

    @property
    def viewer_session_id(self) -> str:
        return self._viewer_session_id

    @property
    def evidence_writer(self) -> ControlEvidenceWriter:
        return self._evidence

    @property
    def mock_session(self) -> MockActuatorSession | None:
        return self._session

    async def start(self) -> None:
        if self._started:
            return
        self._subscriber = self._bus.subscribe(maxsize=256)
        self._started = True
        await self.refresh_discovery()
        self._task = asyncio.create_task(self._consume_events())
        self._append_evidence(
            {
                "event": "CONTROL_SERVICE_STARTED",
                "viewer_session_id": self._viewer_session_id,
                "mock_only": True,
            },
            required=False,
        )

    async def close(self) -> None:
        if not self._started:
            return
        if self._supervisor is not None and self._supervisor.control_mode is ControlMode.ENABLED:
            try:
                await self.disable()
            except Exception as exc:
                self._last_service_error = str(exc) or type(exc).__name__
        if self._subscriber is not None:
            while True:
                try:
                    self._subscriber.put_nowait(self._stop_sentinel)  # type: ignore[arg-type]
                    break
                except Full:
                    try:
                        self._subscriber.get_nowait()
                    except Exception:
                        break
        if self._task is not None:
            await self._task
        if self._subscriber is not None:
            self._bus.unsubscribe(self._subscriber)
        if self._session is not None:
            await self._session.disconnect()
        self._subscriber = None
        self._task = None
        self._started = False

    async def _consume_events(self) -> None:
        assert self._subscriber is not None
        while True:
            item = await asyncio.to_thread(self._subscriber.get)
            if item is self._stop_sentinel:
                return
            await self._handle_runtime_event(item)

    async def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, MeasurementSample):
            self._latest_samples[event.identity.device_id] = event
        supervisor = self._supervisor
        if supervisor is None:
            return

        now_ns = time.monotonic_ns()
        now_utc = datetime.now(timezone.utc)
        timeout_decision = supervisor.check_ack_timeout(
            now_monotonic_ns=now_ns,
            now_utc=now_utc,
        )
        await self._apply_decision(timeout_decision, now_monotonic_ns=now_ns)

        if isinstance(event, MeasurementSample):
            decision = supervisor.observe_sample(
                event,
                now_monotonic_ns=now_ns,
                now_utc=now_utc,
            )
        elif isinstance(event, DiagnosticEvent):
            decision = supervisor.observe_diagnostic(event, now_utc=now_utc)
        else:
            return
        await self._apply_decision(decision, now_monotonic_ns=now_ns)

    def _mode(self) -> ControlMode:
        if self._supervisor is None:
            return ControlMode.DISABLED
        return self._supervisor.control_mode

    def _require_disabled(self) -> None:
        if self._mode() is not ControlMode.DISABLED:
            raise LoadControlCommandError("load-control configuration can change only while DISABLED")

    async def configure_binding(self, *, emonio_device_id: str, actuator_node_id: str) -> None:
        self._require_disabled()
        if not isinstance(emonio_device_id, str) or not emonio_device_id:
            raise LoadControlCommandError("emonio_device_id is required")
        if not isinstance(actuator_node_id, str) or not actuator_node_id:
            raise LoadControlCommandError("actuator_node_id is required")
        updated = replace(
            self._config,
            bound_emonio_device_id=emonio_device_id,
            bound_actuator_node_id=actuator_node_id,
        )
        self._config_store.replace(updated)
        self._config = updated
        await self._rebuild_supervisor_and_session()
        self._append_evidence(
            {
                "event": "CONTROL_BINDING_CHANGED",
                "emonio_device_id": emonio_device_id,
                "actuator_node_id": actuator_node_id,
            },
            required=False,
        )

    async def configure_limits(
        self,
        *,
        p_reserve: float,
        operator_limit_a: float,
        operator_limit_b: float,
        operator_limit_c: float,
    ) -> None:
        self._require_disabled()
        try:
            updated = replace(
                self._config,
                p_reserve=float(p_reserve),
                operator_limit_a=float(operator_limit_a),
                operator_limit_b=float(operator_limit_b),
                operator_limit_c=float(operator_limit_c),
            )
        except (TypeError, ValueError) as exc:
            raise LoadControlCommandError(str(exc) or "invalid load-control limits") from exc
        self._config_store.replace(updated)
        self._config = updated
        await self._rebuild_supervisor_and_session()
        self._append_evidence(
            {
                "event": "CONTROL_LIMITS_CHANGED",
                "p_reserve": updated.p_reserve,
                "operator_limit_a": updated.operator_limit_a,
                "operator_limit_b": updated.operator_limit_b,
                "operator_limit_c": updated.operator_limit_c,
            },
            required=False,
        )

    async def configure_timing(
        self,
        *,
        control_sample_max_age_s: float,
        ack_timeout_s: float,
    ) -> None:
        self._require_disabled()
        try:
            timing = LoadControlTiming(
                control_sample_max_age_s=float(control_sample_max_age_s),
                ack_timeout_s=float(ack_timeout_s),
            )
        except (TypeError, ValueError) as exc:
            raise LoadControlCommandError(str(exc) or "invalid load-control timing") from exc
        self._timing = timing
        await self._rebuild_supervisor_and_session()
        self._append_evidence(
            {
                "event": "CONTROL_TIMING_QUALIFICATION_SET",
                "control_sample_max_age_s": timing.control_sample_max_age_s,
                "ack_timeout_s": timing.ack_timeout_s,
                "persistent": False,
            },
            required=False,
        )

    async def refresh_discovery(self) -> tuple[ActuatorDescriptor, ...]:
        self._visible = await self._discovery.discover()
        await self._connect_bound_mock()
        return self._visible

    async def _rebuild_supervisor_and_session(self) -> None:
        old_session = self._session
        if old_session is not None:
            await old_session.disconnect()
        self._session = None
        self._hello = None
        if self._timing is None:
            self._supervisor = None
        else:
            self._supervisor = LoadControlSupervisor(
                self._config,
                self._timing,
                viewer_session_id=self._viewer_session_id,
            )
        await self.refresh_discovery()
        if self._supervisor is not None:
            source = self._config.bound_emonio_device_id
            sample = None if source is None else self._latest_samples.get(source)
            if sample is not None:
                decision = self._supervisor.observe_sample(
                    sample,
                    now_monotonic_ns=time.monotonic_ns(),
                    now_utc=datetime.now(timezone.utc),
                )
                await self._apply_decision(decision, now_monotonic_ns=time.monotonic_ns())

    async def _connect_bound_mock(self) -> None:
        bound = self._config.bound_actuator_node_id
        if bound is None:
            return
        descriptor = next((item for item in self._visible if item.node_id == bound), None)
        if descriptor is None:
            if self._supervisor is not None:
                self._supervisor.session_state = SessionState.UNAVAILABLE
            return
        if self._session is not None and self._session.descriptor.node_id == descriptor.node_id:
            return
        self._session = MockActuatorSession(
            descriptor,
            boot_id=self._mock_boot_id,
            ack_mode=MockAckMode.EXACT,
        )
        self._hello = await self._session.connect()
        if self._supervisor is not None:
            decision = self._supervisor.qualify_session(
                self._hello,
                now_monotonic_ns=time.monotonic_ns(),
            )
            await self._apply_decision(decision, now_monotonic_ns=time.monotonic_ns())

    async def enable(self) -> None:
        if self._supervisor is None:
            raise LoadControlCommandError("control timing is not qualified for this Viewer session")
        try:
            self._supervisor.enable(
                evidence_healthy=self._evidence.healthy,
                now_monotonic_ns=time.monotonic_ns(),
            )
        except EnableRejected as exc:
            self._append_evidence(
                {"event": "CONTROL_ENABLE_REJECTED", "reason": str(exc)},
                required=False,
            )
            raise LoadControlCommandError(str(exc)) from exc
        self._append_evidence({"event": "CONTROL_ENABLE_ACCEPTED"}, required=True)

    async def disable(self) -> None:
        if self._supervisor is None:
            return
        decision = self._supervisor.disable(
            now_utc=datetime.now(timezone.utc),
            now_monotonic_ns=time.monotonic_ns(),
        )
        await self._apply_decision(decision, now_monotonic_ns=time.monotonic_ns())

    async def _apply_decision(
        self,
        decision: SupervisorDecision,
        *,
        now_monotonic_ns: int,
    ) -> None:
        command = decision.command
        event_payload: dict[str, Any] | None = None
        if decision.event is not None:
            event_payload = {
                "event": decision.event,
                "reason": decision.reason,
                "viewer_session_id": self._viewer_session_id,
            }
            if command is not None:
                event_payload.update(
                    {
                        "node_id": command.node_id,
                        "boot_id": command.boot_id,
                        "sequence": command.sequence,
                        "emonio_device_id": command.emonio_device_id,
                        "measurement_cycle_id": command.measurement_cycle_id,
                        "measurement_utc": command.measurement_utc,
                        "command_utc": command.command_utc,
                        "control_enabled": command.control_enabled,
                        "measured_p": self._power_json(command.measured_p),
                        "measured_q": self._power_json(command.measured_q),
                        "p_load_request": self._power_json(command.p_load_request),
                        "q_comp_request": self._power_json(command.q_comp_request),
                    }
                )
            if decision.calculation is not None:
                event_payload["calculation"] = {
                    phase: {
                        "error": getattr(decision.calculation, phase).error,
                        "raw_request": getattr(decision.calculation, phase).raw_request,
                        "limited_request": getattr(decision.calculation, phase).limited_request,
                        "limited_min": getattr(decision.calculation, phase).limited_min,
                        "limited_max": getattr(decision.calculation, phase).limited_max,
                    }
                    for phase in ("a", "b", "c")
                }

        required_before_send = bool(
            command is not None
            and command.control_enabled
            and any(value > 0.0 for value in (command.p_load_request.a, command.p_load_request.b, command.p_load_request.c))
        )
        if event_payload is not None:
            try:
                self._append_evidence(event_payload, required=required_before_send)
            except EvidenceWriteError:
                if required_before_send:
                    self._last_service_error = "required control evidence could not be written"
                    await self.disable()
                    return

        if command is None:
            return
        if self._session is None or not self._session.connected:
            self._last_service_error = "mock actuator session is unavailable"
            if self._supervisor is not None:
                lost = self._supervisor.session_lost()
                if lost.event is not None:
                    self._append_evidence(
                        {"event": lost.event, "reason": lost.reason},
                        required=False,
                    )
            return

        await self._session.send_command(command)
        self._append_evidence(
            {
                "event": "CONTROL_COMMAND_SENT",
                "sequence": command.sequence,
                "control_enabled": command.control_enabled,
                "p_load_request": self._power_json(command.p_load_request),
            },
            required=False,
        )
        ack = await self._session.receive_ack()
        if ack is None or self._supervisor is None:
            return
        ack_decision = self._supervisor.accept_ack(
            ack,
            now_monotonic_ns=now_monotonic_ns,
        )
        self._append_evidence(
            {
                "event": ack_decision.event or "CONTROL_ACK_OBSERVED",
                "reason": ack_decision.reason,
                "sequence": ack.sequence,
                "applied_p": self._power_json(ack.applied_p),
                "result": ack.result,
            },
            required=False,
        )
        if ack_decision.command is not None:
            await self._apply_decision(ack_decision, now_monotonic_ns=now_monotonic_ns)

    def _append_evidence(self, event: dict[str, Any], *, required: bool) -> None:
        try:
            self._evidence.append(event)
        except EvidenceWriteError:
            if required:
                raise
            self._last_service_error = self._evidence.last_error

    @staticmethod
    def _power_json(value: ThreePhasePower) -> dict[str, float]:
        return {"a": value.a, "b": value.b, "c": value.c}

    def status(self) -> dict[str, Any]:
        supervisor = self._supervisor
        acknowledged = None if supervisor is None else supervisor.acknowledged_p
        outstanding = None if supervisor is None else supervisor.outstanding_command
        return {
            "stage": "STAGE_1_MOCK_ONLY",
            "mock_only": True,
            "viewer_session_id": self._viewer_session_id,
            "control_mode": self._mode().value,
            "session_state": (
                SessionState.UNBOUND.value
                if self._config.bound_actuator_node_id is None
                else (SessionState.UNAVAILABLE.value if supervisor is None else supervisor.session_state.value)
            ),
            "safe_state": SafeState.SAFE_UNCONFIRMED.value if supervisor is None else supervisor.safe_state.value,
            "trip_reason": None if supervisor is None else supervisor.trip_reason,
            "config": {
                "bound_emonio_device_id": self._config.bound_emonio_device_id,
                "bound_actuator_node_id": self._config.bound_actuator_node_id,
                "p_reserve": self._config.p_reserve,
                "operator_limit_a": self._config.operator_limit_a,
                "operator_limit_b": self._config.operator_limit_b,
                "operator_limit_c": self._config.operator_limit_c,
            },
            "timing": None
            if self._timing is None
            else {
                "control_sample_max_age_s": self._timing.control_sample_max_age_s,
                "ack_timeout_s": self._timing.ack_timeout_s,
                "persistent": False,
            },
            "actuator_boot_id": None if supervisor is None else supervisor.actuator_boot_id,
            "acknowledged_p": None if acknowledged is None else self._power_json(acknowledged),
            "outstanding_sequence": None if outstanding is None else outstanding.sequence,
            "last_source_cycle_id": None if supervisor is None else supervisor.last_source_cycle_id,
            "last_sample_age_s": None if supervisor is None else supervisor.last_sample_age_s,
            "evidence_healthy": self._evidence.healthy,
            "evidence_error": self._evidence.last_error,
            "last_service_error": self._last_service_error,
            "discovered_actuators": [
                {
                    "node_id": item.node_id,
                    "location": item.location,
                    "device_class": item.device_class,
                    "capabilities": list(item.capabilities),
                    "p_max": self._power_json(item.p_max),
                }
                for item in self._visible
            ],
        }

    def recent_evidence(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        return self._evidence.recent(limit)
