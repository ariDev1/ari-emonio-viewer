from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import math
from queue import Empty, Queue
import time
from typing import Callable

from emonio_viewer.config.model import DeviceConfig, RuntimeConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import (
    DiagnosticEvent as RuntimeDiagnosticEvent,
    RuntimeEvent,
    RuntimeEventBus,
)

from .diagnostic_log import DiagnosticEvent as LoadControlDiagnosticEvent
from .diagnostic_log import LoadControlDiagnosticLog
from .manual_pwm import ManualPwmStatus, PWM_DUTY_CONTROL_CAPABILITY
from .qualification import QualificationStatus


ACTIVE_DUTY_MIN_PERCENT = 25.0
ACTIVE_DUTY_MAX_PERCENT = 75.0
SAFE_DUTY_PERCENT = 0.0
_EVENT_QUEUE_WAIT_S = 0.05
_ACQUISITION_EVENT_PREFIX = "ACQUISITION_"


class PControlDecision(str, Enum):
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    DECREASE = "DECREASE"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"


class PControlObserverState(str, Enum):
    DISABLED = "DISABLED"
    WAITING_FOR_SAMPLE = "WAITING_FOR_SAMPLE"
    OBSERVING = "OBSERVING"
    TARGET_BAND = "TARGET_BAND"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"
    BLOCKED = "BLOCKED"


class PControlObserverError(RuntimeError):
    """Raised when a Stage 4A observer operation is not admissible."""


@dataclass(frozen=True, slots=True)
class PControlProposal:
    decision: PControlDecision
    proposed_duty_percent: float
    low_w: float
    high_w: float


@dataclass(frozen=True, slots=True)
class PControlObserverSettings:
    source_id: str | None = None
    phase: str | None = None
    p_target_w: float | None = None
    p_deadband_w: float | None = None
    duty_step_percent: float | None = None


@dataclass(frozen=True, slots=True)
class PControlObserverStatus:
    state: PControlObserverState
    reason: str | None
    source_id: str | None
    phase: str | None
    sample_cycle_id: int | None
    measured_p_w: float | None
    measured_q_var: float | None
    sample_quality: str | None
    sample_age_s: float | None
    p_target_w: float | None
    p_deadband_w: float | None
    duty_step_percent: float | None
    actuator_node_id: str | None
    actuator_boot_id: str | None
    confirmed_command_sequence: int | None
    confirmed_requested_duty_percent: float | None
    confirmed_actual_duty_percent: float | None
    decision: PControlDecision | None
    proposed_duty_percent: float | None


@dataclass(frozen=True, slots=True)
class _ConfirmedPwmEvidence:
    node_id: str
    boot_id: str
    command_sequence: int
    requested_duty_percent: float
    actual_duty_percent: float | None

    @property
    def fingerprint(self) -> tuple[str, str, int, float]:
        return (
            self.node_id,
            self.boot_id,
            self.command_sequence,
            self.requested_duty_percent,
        )


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _valid_poll_interval(value: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _validated_confirmed_duty(value: float) -> float:
    duty = _finite("confirmed_duty_percent", value)
    if duty == SAFE_DUTY_PERCENT:
        return duty
    if ACTIVE_DUTY_MIN_PERCENT <= duty <= ACTIVE_DUTY_MAX_PERCENT:
        return duty
    raise ValueError("confirmed_duty_percent is outside the Stage 4A qualified window")


def calculate_p_control_proposal(
    *,
    measured_p_w: float,
    p_target_w: float,
    p_deadband_w: float,
    confirmed_duty_percent: float,
    duty_step_percent: float,
) -> PControlProposal:
    measured_p = _finite("measured_p_w", measured_p_w)
    target = _finite("p_target_w", p_target_w)
    deadband = _finite("p_deadband_w", p_deadband_w)
    duty = _validated_confirmed_duty(confirmed_duty_percent)
    step = _finite("duty_step_percent", duty_step_percent)

    if deadband < 0.0:
        raise ValueError("p_deadband_w must be >= 0")
    if step <= 0.0:
        raise ValueError("duty_step_percent must be > 0")

    low = target - deadband
    high = target + deadband

    if measured_p < low:
        if duty == ACTIVE_DUTY_MAX_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_HIGH, duty, low, high)
        if duty == SAFE_DUTY_PERCENT:
            return PControlProposal(
                PControlDecision.INCREASE,
                ACTIVE_DUTY_MIN_PERCENT,
                low,
                high,
            )
        return PControlProposal(
            PControlDecision.INCREASE,
            min(duty + step, ACTIVE_DUTY_MAX_PERCENT),
            low,
            high,
        )

    if measured_p > high:
        if duty == SAFE_DUTY_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_LOW, duty, low, high)
        if duty == ACTIVE_DUTY_MIN_PERCENT:
            return PControlProposal(
                PControlDecision.DECREASE,
                SAFE_DUTY_PERCENT,
                low,
                high,
            )
        return PControlProposal(
            PControlDecision.DECREASE,
            max(duty - step, ACTIVE_DUTY_MIN_PERCENT),
            low,
            high,
        )

    return PControlProposal(PControlDecision.HOLD, duty, low, high)


class PControlObserverService:
    """Calculate P-only duty proposals without actuator command authority."""

    def __init__(
        self,
        bus: RuntimeEventBus,
        config: RuntimeConfig,
        *,
        qualification_status: Callable[[], QualificationStatus],
        manual_pwm_status: Callable[[], ManualPwmStatus | None],
        diagnostic_log: LoadControlDiagnosticLog | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        if not isinstance(bus, RuntimeEventBus):
            raise ValueError("bus must be RuntimeEventBus")
        if not isinstance(config, RuntimeConfig):
            raise ValueError("config must be RuntimeConfig")
        if not callable(qualification_status):
            raise ValueError("qualification_status must be callable")
        if not callable(manual_pwm_status):
            raise ValueError("manual_pwm_status must be callable")

        self._bus = bus
        self._config = config
        self._qualification_status = qualification_status
        self._manual_pwm_status = manual_pwm_status
        self._diagnostic_log = diagnostic_log or LoadControlDiagnosticLog()
        self._monotonic_ns = monotonic_ns or time.monotonic_ns

        self._settings = PControlObserverSettings()
        self._state = PControlObserverState.DISABLED
        self._reason: str | None = None
        self._subscriber: Queue[RuntimeEvent] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._stop_sentinel = object()
        self._started = False

        self._latest_cycle_by_source: dict[str, int] = {}
        self._last_source_cycle_id: int | None = None
        self._enable_boundary_cycle = 0
        self._enable_monotonic_ns = 0
        self._freshness_deadline_ns: int | None = None
        self._baseline: _ConfirmedPwmEvidence | None = None

        self._sample_cycle_id: int | None = None
        self._measured_p_w: float | None = None
        self._measured_q_var: float | None = None
        self._sample_quality: str | None = None
        self._sample_finished_monotonic_ns: int | None = None
        self._decision: PControlDecision | None = None
        self._proposed_duty_percent: float | None = None

    def _source_config(self, device_id: str | None) -> DeviceConfig | None:
        if not isinstance(device_id, str) or not device_id:
            return None
        matches = tuple(
            item
            for item in self._config.devices
            if item.enabled
            and item.id == device_id
            and _valid_poll_interval(item.poll_interval_s)
        )
        return matches[0] if len(matches) == 1 else None

    def _freshness_ns(self) -> int:
        source = self._source_config(self._settings.source_id)
        if source is None:
            raise PControlObserverError("SOURCE_NOT_AVAILABLE")
        return int(2.0 * float(source.poll_interval_s) * 1_000_000_000)

    def configure(
        self,
        *,
        source_id: str,
        phase: str,
        p_target_w: float,
        p_deadband_w: float,
        duty_step_percent: float,
    ) -> PControlObserverStatus:
        if self._state is not PControlObserverState.DISABLED:
            raise PControlObserverError("OBSERVER_NOT_DISABLED")
        if self._source_config(source_id) is None:
            raise PControlObserverError("SOURCE_NOT_AVAILABLE")
        if phase not in {"A", "B", "C"}:
            raise PControlObserverError("PHASE_NOT_SELECTED")
        try:
            target = _finite("p_target_w", p_target_w)
            deadband = _finite("p_deadband_w", p_deadband_w)
            step = _finite("duty_step_percent", duty_step_percent)
            if deadband < 0.0 or step <= 0.0:
                raise ValueError("invalid Stage 4A parameter")
        except ValueError as exc:
            raise PControlObserverError("PARAMETER_INVALID") from exc

        settings = PControlObserverSettings(
            source_id=source_id,
            phase=phase,
            p_target_w=target,
            p_deadband_w=deadband,
            duty_step_percent=step,
        )
        self._settings = settings
        self._reason = None
        return self.status()

    def _current_pwm_evidence(self, *, active: bool) -> _ConfirmedPwmEvidence:
        qualification = self._qualification_status()
        if not qualification.connected or not qualification.hello_qualified:
            reason = "ACTUATOR_DISCONNECTED" if active else "ACTUATOR_NOT_QUALIFIED"
            raise PControlObserverError(reason)

        baseline = self._baseline
        if (
            active
            and baseline is not None
            and qualification.boot_id is not None
            and qualification.boot_id != baseline.boot_id
        ):
            raise PControlObserverError("ACTUATOR_BOOT_CHANGED")

        if PWM_DUTY_CONTROL_CAPABILITY not in qualification.capabilities:
            raise PControlObserverError("PWM_DUTY_CONTROL_NOT_SUPPORTED")

        manual = self._manual_pwm_status()
        if manual is None:
            raise PControlObserverError("CONFIRMED_DUTY_UNKNOWN")
        if (
            active
            and baseline is not None
            and manual.boot_id is not None
            and manual.boot_id != baseline.boot_id
        ):
            raise PControlObserverError("ACTUATOR_BOOT_CHANGED")
        if (
            manual.ack_result != "APPLIED"
            or manual.command_sequence is None
            or manual.requested_duty_percent is None
            or qualification.node_id is None
            or qualification.boot_id is None
            or manual.node_id != qualification.node_id
            or manual.boot_id != qualification.boot_id
        ):
            raise PControlObserverError("CONFIRMED_DUTY_UNKNOWN")

        try:
            requested = _validated_confirmed_duty(manual.requested_duty_percent)
        except ValueError as exc:
            raise PControlObserverError(
                "CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW"
            ) from exc

        actual: float | None = None
        if manual.actual_duty_percent is not None:
            try:
                actual = _finite("actual_duty_percent", manual.actual_duty_percent)
            except ValueError:
                actual = None

        return _ConfirmedPwmEvidence(
            node_id=qualification.node_id,
            boot_id=qualification.boot_id,
            command_sequence=manual.command_sequence,
            requested_duty_percent=requested,
            actual_duty_percent=actual,
        )

    def _clear_sample_result(self) -> None:
        self._sample_cycle_id = None
        self._measured_p_w = None
        self._measured_q_var = None
        self._sample_quality = None
        self._sample_finished_monotonic_ns = None
        self._decision = None
        self._proposed_duty_percent = None

    async def start(self) -> None:
        if self._started:
            return
        self._subscriber = self._bus.subscribe(maxsize=256)
        self._started = True
        self._consumer_task = asyncio.create_task(self._consume_events())

    async def close(self) -> None:
        if self._started and self._subscriber is not None:
            await asyncio.to_thread(self._subscriber.put, self._stop_sentinel)  # type: ignore[arg-type]
            if self._consumer_task is not None:
                await self._consumer_task
            self._bus.unsubscribe(self._subscriber)
        self._subscriber = None
        self._consumer_task = None
        self._started = False
        self._freshness_deadline_ns = None
        self._baseline = None
        self._state = PControlObserverState.DISABLED
        self._reason = None
        self._clear_sample_result()

    async def enable(self) -> PControlObserverStatus:
        if not self._started:
            raise PControlObserverError("OBSERVER_NOT_STARTED")
        if self._state is not PControlObserverState.DISABLED:
            raise PControlObserverError("OBSERVER_NOT_DISABLED")
        if self._source_config(self._settings.source_id) is None:
            self._reason = "SOURCE_NOT_AVAILABLE"
            raise PControlObserverError(self._reason)
        if self._settings.phase not in {"A", "B", "C"}:
            self._reason = "PHASE_NOT_SELECTED"
            raise PControlObserverError(self._reason)
        if (
            self._settings.p_target_w is None
            or self._settings.p_deadband_w is None
            or self._settings.duty_step_percent is None
        ):
            self._reason = "PARAMETER_INVALID"
            raise PControlObserverError(self._reason)

        try:
            evidence = self._current_pwm_evidence(active=False)
        except PControlObserverError as exc:
            self._reason = str(exc)
            self._decision = None
            self._proposed_duty_percent = None
            raise

        now = self._monotonic_ns()
        boundary = self._latest_cycle_by_source.get(self._settings.source_id or "", 0)
        self._baseline = evidence
        self._enable_boundary_cycle = boundary
        self._last_source_cycle_id = boundary
        self._enable_monotonic_ns = now
        self._clear_sample_result()
        self._state = PControlObserverState.WAITING_FOR_SAMPLE
        self._reason = None
        self._freshness_deadline_ns = now + self._freshness_ns()
        self._diagnostic_log.append(
            "P_OBSERVER_ENABLED",
            emonio_device_id=self._settings.source_id,
            phase=self._settings.phase,
            actuator_node_id=evidence.node_id,
            actuator_boot_id=evidence.boot_id,
            confirmed_requested_duty_percent=evidence.requested_duty_percent,
        )
        return self.status()

    async def disable(self) -> PControlObserverStatus:
        self._state = PControlObserverState.DISABLED
        self._reason = None
        self._freshness_deadline_ns = None
        self._last_source_cycle_id = None
        self._enable_boundary_cycle = 0
        self._enable_monotonic_ns = 0
        self._baseline = None
        self._clear_sample_result()
        self._diagnostic_log.append("P_OBSERVER_DISABLED")
        return self.status()

    def status(self) -> PControlObserverStatus:
        baseline = self._baseline
        age: float | None = None
        if self._sample_finished_monotonic_ns is not None:
            age = max(
                0.0,
                (self._monotonic_ns() - self._sample_finished_monotonic_ns)
                / 1_000_000_000.0,
            )
        return PControlObserverStatus(
            state=self._state,
            reason=self._reason,
            source_id=self._settings.source_id,
            phase=self._settings.phase,
            sample_cycle_id=self._sample_cycle_id,
            measured_p_w=self._measured_p_w,
            measured_q_var=self._measured_q_var,
            sample_quality=self._sample_quality,
            sample_age_s=age,
            p_target_w=self._settings.p_target_w,
            p_deadband_w=self._settings.p_deadband_w,
            duty_step_percent=self._settings.duty_step_percent,
            actuator_node_id=(baseline.node_id if baseline is not None else None),
            actuator_boot_id=(baseline.boot_id if baseline is not None else None),
            confirmed_command_sequence=(
                baseline.command_sequence if baseline is not None else None
            ),
            confirmed_requested_duty_percent=(
                baseline.requested_duty_percent if baseline is not None else None
            ),
            confirmed_actual_duty_percent=(
                baseline.actual_duty_percent if baseline is not None else None
            ),
            decision=self._decision,
            proposed_duty_percent=self._proposed_duty_percent,
        )

    def diagnostics(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[LoadControlDiagnosticEvent, ...]:
        return self._diagnostic_log.recent(after_sequence=after_sequence, limit=limit)

    def _block(self, reason: str) -> None:
        if self._state is PControlObserverState.BLOCKED:
            return
        self._state = PControlObserverState.BLOCKED
        self._reason = reason
        self._decision = None
        self._proposed_duty_percent = None
        self._freshness_deadline_ns = None
        self._diagnostic_log.append("P_OBSERVER_BLOCKED", reason=reason)

    def _check_deadline(self) -> None:
        if self._state in {
            PControlObserverState.DISABLED,
            PControlObserverState.BLOCKED,
        }:
            return
        deadline = self._freshness_deadline_ns
        if deadline is None or self._monotonic_ns() <= deadline:
            return
        try:
            self._current_pwm_evidence(active=True)
        except PControlObserverError as exc:
            self._block(str(exc))
            return
        self._block("SAMPLE_STALE")

    async def _consume_events(self) -> None:
        assert self._subscriber is not None
        while True:
            try:
                item = await asyncio.to_thread(
                    self._subscriber.get,
                    True,
                    _EVENT_QUEUE_WAIT_S,
                )
            except Empty:
                self._check_deadline()
                continue
            if item is self._stop_sentinel:
                return
            self._handle_runtime_event(item)
            self._check_deadline()

    def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, MeasurementSample):
            self._handle_measurement(event)
        elif isinstance(event, RuntimeDiagnosticEvent):
            self._handle_runtime_diagnostic(event)

    def _handle_runtime_diagnostic(self, event: RuntimeDiagnosticEvent) -> None:
        if self._state in {
            PControlObserverState.DISABLED,
            PControlObserverState.BLOCKED,
        }:
            return
        if event.device_id != self._settings.source_id:
            return
        if event.cycle_id <= self._enable_boundary_cycle:
            return
        if event.event.startswith(_ACQUISITION_EVENT_PREFIX):
            self._block("ACQUISITION_FAILURE")

    def _handle_measurement(self, sample: MeasurementSample) -> None:
        device_id = sample.identity.device_id
        cycle_id = sample.identity.cycle_id
        previous_latest = self._latest_cycle_by_source.get(device_id, 0)
        if cycle_id > previous_latest:
            self._latest_cycle_by_source[device_id] = cycle_id

        if self._state in {
            PControlObserverState.DISABLED,
            PControlObserverState.BLOCKED,
        }:
            return
        if device_id != self._settings.source_id:
            self._diagnostic_log.append(
                "P_OBSERVER_SAMPLE_IGNORED",
                emonio_device_id=device_id,
                measurement_cycle_id=cycle_id,
                reason="SOURCE_MISMATCH",
            )
            return

        last_cycle = self._last_source_cycle_id
        if last_cycle is not None and cycle_id <= last_cycle:
            return
        if last_cycle is not None and cycle_id != last_cycle + 1:
            self._block("SAMPLE_SEQUENCE_GAP")
            return
        self._last_source_cycle_id = cycle_id

        if self._state is PControlObserverState.WAITING_FOR_SAMPLE:
            if cycle_id <= self._enable_boundary_cycle:
                return
            if sample.timing.cycle_started_monotonic_ns <= self._enable_monotonic_ns:
                self._enable_boundary_cycle = cycle_id
                return

        if sample.quality is not SampleQuality.VALID:
            self._block("SAMPLE_NOT_VALID")
            return

        now = self._monotonic_ns()
        age_ns = now - sample.timing.cycle_finished_monotonic_ns
        if age_ns < 0 or age_ns > self._freshness_ns():
            self._block("SAMPLE_STALE")
            return

        try:
            evidence = self._current_pwm_evidence(active=True)
        except PControlObserverError as exc:
            self._block(str(exc))
            return

        baseline = self._baseline
        if baseline is None:
            self._block("CONFIRMED_DUTY_UNKNOWN")
            return
        if evidence.fingerprint != baseline.fingerprint:
            self._baseline = evidence
            self._sample_cycle_id = cycle_id
            self._measured_p_w = None
            self._measured_q_var = None
            self._sample_quality = sample.quality.value
            self._sample_finished_monotonic_ns = sample.timing.cycle_finished_monotonic_ns
            self._decision = None
            self._proposed_duty_percent = None
            self._state = PControlObserverState.WAITING_FOR_SAMPLE
            self._reason = None
            self._enable_boundary_cycle = cycle_id
            self._enable_monotonic_ns = sample.timing.cycle_finished_monotonic_ns
            self._freshness_deadline_ns = now + self._freshness_ns()
            self._diagnostic_log.append(
                "P_OBSERVER_DUTY_BASELINE_CHANGED",
                actuator_node_id=evidence.node_id,
                actuator_boot_id=evidence.boot_id,
                command_sequence=evidence.command_sequence,
                confirmed_requested_duty_percent=evidence.requested_duty_percent,
                measurement_cycle_id=cycle_id,
            )
            return

        phase = self._settings.phase
        if phase == "A":
            block = sample.phase_a
        elif phase == "B":
            block = sample.phase_b
        elif phase == "C":
            block = sample.phase_c
        else:
            self._block("PHASE_NOT_SELECTED")
            return

        assert self._settings.p_target_w is not None
        assert self._settings.p_deadband_w is not None
        assert self._settings.duty_step_percent is not None
        proposal = calculate_p_control_proposal(
            measured_p_w=block.measurement.p,
            p_target_w=self._settings.p_target_w,
            p_deadband_w=self._settings.p_deadband_w,
            confirmed_duty_percent=evidence.requested_duty_percent,
            duty_step_percent=self._settings.duty_step_percent,
        )

        self._baseline = evidence
        self._sample_cycle_id = cycle_id
        self._measured_p_w = block.measurement.p
        self._measured_q_var = block.measurement.q
        self._sample_quality = sample.quality.value
        self._sample_finished_monotonic_ns = sample.timing.cycle_finished_monotonic_ns
        self._decision = proposal.decision
        self._proposed_duty_percent = proposal.proposed_duty_percent
        self._reason = None

        if proposal.decision is PControlDecision.HOLD:
            self._state = PControlObserverState.TARGET_BAND
        elif proposal.decision is PControlDecision.LIMIT_LOW:
            self._state = PControlObserverState.LIMIT_LOW
        elif proposal.decision is PControlDecision.LIMIT_HIGH:
            self._state = PControlObserverState.LIMIT_HIGH
        else:
            self._state = PControlObserverState.OBSERVING

        self._freshness_deadline_ns = (
            sample.timing.cycle_finished_monotonic_ns + self._freshness_ns()
        )
        self._diagnostic_log.append(
            "P_OBSERVER_PROPOSAL_CALCULATED",
            emonio_device_id=device_id,
            phase=phase,
            measurement_cycle_id=cycle_id,
            measured_p_w=block.measurement.p,
            p_target_w=self._settings.p_target_w,
            p_deadband_w=self._settings.p_deadband_w,
            confirmed_requested_duty_percent=evidence.requested_duty_percent,
            duty_step_percent=self._settings.duty_step_percent,
            decision=proposal.decision.value,
            proposed_duty_percent=proposal.proposed_duty_percent,
            observer_state=self._state.value,
        )
