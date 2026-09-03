from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import math
from queue import Empty, Full, Queue
import time
from typing import Callable, Protocol

from emonio_viewer.config.model import DeviceConfig, RuntimeConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEvent, RuntimeEventBus

from .diagnostic_log import LoadControlDiagnosticLog
from .manual_pwm import ManualPwmState, ManualPwmStatus
from .stage3a import Stage3AError
from .zero_export import (
    ZeroExportAction,
    calculate_zero_export_step,
)


ZERO_EXPORT_PWM_OWNER = "STAGE4C_ZERO_EXPORT"
_EVENT_QUEUE_WAIT_S = 0.05
_ACQUISITION_EVENT_PREFIX = "ACQUISITION_"


class ZeroExportControllerState(str, Enum):
    DISABLED = "DISABLED"
    ENABLING = "ENABLING"
    WAITING_FOR_SAMPLE = "WAITING_FOR_SAMPLE"
    SETTLING = "SETTLING"
    CONTROLLING = "CONTROLLING"
    TARGET_BAND = "TARGET_BAND"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"
    RESOLUTION_LIMIT = "RESOLUTION_LIMIT"
    SAFE_OFF = "SAFE_OFF"
    BLOCKED_SAFE = "BLOCKED_SAFE"
    SAFE_UNCONFIRMED = "SAFE_UNCONFIRMED"


class Stage4CZeroExportControllerError(RuntimeError):
    """Raised when an automatic zero-export operation is not admissible."""


class _ManualPwmInterface(Protocol):
    @property
    def pwm_owner(self) -> str | None: ...

    def manual_pwm_status(self) -> ManualPwmStatus: ...

    def reserve_pwm_owner(self, owner: str) -> None: ...

    def release_pwm_owner(self, owner: str) -> None: ...

    async def run_reserved_pwm(
        self,
        duty_percent: float,
        *,
        owner: str,
    ) -> ManualPwmStatus: ...


@dataclass(frozen=True, slots=True)
class ZeroExportControllerSettings:
    source_id: str
    phase: str
    p_deadband_w: float


@dataclass(frozen=True, slots=True)
class ZeroExportControllerStatus:
    state: ZeroExportControllerState
    reason: str | None
    source_id: str | None
    phase: str | None
    p_deadband_w: float | None
    sample_cycle_id: int | None
    measured_p_w: float | None
    sample_quality: str | None
    action: str | None
    lower_bracket_duty_percent: float | None
    upper_bracket_duty_percent: float | None
    actuator_node_id: str | None
    actuator_boot_id: str | None
    command_sequence: int | None
    confirmed_requested_duty_percent: float | None
    confirmed_actual_duty_percent: float | None
    confirmed_compare_ticks: int | None
    confirmed_period_ticks: int | None
    safe_confirmed: bool | None


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _valid_poll_interval(value: float) -> bool:
    number = _finite(value)
    return number is not None and number > 0.0


class Stage4CZeroExportControllerService:
    """Bounded automatic zero-export controller.

    Canonical phase P is the only measurement feedback input. The service does
    not read Modbus, alter acquisition, estimate load watts, or use Q/PF. All
    physical PWM commands use the existing reserved manual PWM command/ACK
    path. Actuator compare-tick evidence is used only to detect when two
    different requested duties produce the same physical PWM state.
    """

    def __init__(
        self,
        bus: RuntimeEventBus,
        config: RuntimeConfig,
        *,
        manual_pwm: _ManualPwmInterface,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        diagnostic_log: LoadControlDiagnosticLog | None = None,
    ) -> None:
        if not isinstance(bus, RuntimeEventBus):
            raise ValueError("bus must be RuntimeEventBus")
        if not isinstance(config, RuntimeConfig):
            raise ValueError("config must be RuntimeConfig")
        for name in (
            "manual_pwm_status",
            "reserve_pwm_owner",
            "release_pwm_owner",
            "run_reserved_pwm",
        ):
            if not callable(getattr(manual_pwm, name, None)):
                raise ValueError(f"manual_pwm must provide {name}")
        if not callable(monotonic_ns):
            raise ValueError("monotonic_ns must be callable")
        if diagnostic_log is not None and not isinstance(diagnostic_log, LoadControlDiagnosticLog):
            raise ValueError("diagnostic_log must be LoadControlDiagnosticLog")

        self._bus = bus
        self._config = config
        self._manual_pwm = manual_pwm
        self._monotonic_ns = monotonic_ns
        self._diagnostic_log = diagnostic_log or LoadControlDiagnosticLog()
        self._subscriber: Queue[RuntimeEvent] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._stop_sentinel = object()
        self._started = False
        self._enabled = False
        self._owner_reserved = False
        self._settings: ZeroExportControllerSettings | None = None

        self._state = ZeroExportControllerState.DISABLED
        self._reason: str | None = None
        self._sample_cycle_id: int | None = None
        self._measured_p_w: float | None = None
        self._sample_quality: str | None = None
        self._action: ZeroExportAction | None = None
        self._lower_bracket: float | None = None
        self._upper_bracket: float | None = None
        self._actuator_node_id: str | None = None
        self._actuator_boot_id: str | None = None
        self._command_sequence: int | None = None
        self._confirmed_requested_duty: float | None = None
        self._confirmed_actual_duty: float | None = None
        self._confirmed_compare_ticks: int | None = None
        self._confirmed_period_ticks: int | None = None
        self._safe_confirmed: bool | None = None
        self._resolution_limit_direction: ZeroExportAction | None = None

        self._causal_after_ns: int | None = None
        self._settling_pending = False
        self._last_post_ack_cycle: int | None = None
        self._freshness_deadline_ns: int | None = None
        self._operation_lock = asyncio.Lock()

    def status(self) -> ZeroExportControllerStatus:
        settings = self._settings
        return ZeroExportControllerStatus(
            state=self._state,
            reason=self._reason,
            source_id=(settings.source_id if settings is not None else None),
            phase=(settings.phase if settings is not None else None),
            p_deadband_w=(settings.p_deadband_w if settings is not None else None),
            sample_cycle_id=self._sample_cycle_id,
            measured_p_w=self._measured_p_w,
            sample_quality=self._sample_quality,
            action=(self._action.value if self._action is not None else None),
            lower_bracket_duty_percent=self._lower_bracket,
            upper_bracket_duty_percent=self._upper_bracket,
            actuator_node_id=self._actuator_node_id,
            actuator_boot_id=self._actuator_boot_id,
            command_sequence=self._command_sequence,
            confirmed_requested_duty_percent=self._confirmed_requested_duty,
            confirmed_actual_duty_percent=self._confirmed_actual_duty,
            confirmed_compare_ticks=self._confirmed_compare_ticks,
            confirmed_period_ticks=self._confirmed_period_ticks,
            safe_confirmed=self._safe_confirmed,
        )

    def _source_config(self, source_id: str) -> DeviceConfig | None:
        matches = tuple(
            item
            for item in self._config.devices
            if item.enabled
            and item.id == source_id
            and _valid_poll_interval(item.poll_interval_s)
        )
        return matches[0] if len(matches) == 1 else None

    def configure(self, *, source_id: str, phase: str, p_deadband_w: float) -> ZeroExportControllerStatus:
        if self._enabled or self._state not in {ZeroExportControllerState.DISABLED}:
            raise Stage4CZeroExportControllerError("ZERO_EXPORT_ACTIVE")
        source = self._source_config(source_id)
        if source is None:
            raise Stage4CZeroExportControllerError("SOURCE_NOT_AVAILABLE")
        if phase not in {"A", "B", "C"}:
            raise Stage4CZeroExportControllerError("PHASE_NOT_SELECTED")
        deadband = _finite(p_deadband_w)
        if deadband is None or deadband < 0.0:
            raise Stage4CZeroExportControllerError("P_DEADBAND_INVALID")
        self._settings = ZeroExportControllerSettings(
            source_id=source.id,
            phase=phase,
            p_deadband_w=deadband,
        )
        self._reason = None
        return self.status()

    async def start(self) -> None:
        if self._started:
            return
        self._subscriber = self._bus.subscribe(maxsize=256)
        self._started = True
        self._consumer_task = asyncio.create_task(self._consume_events())

    def _queue_private(self, item: object) -> None:
        subscriber = self._subscriber
        if subscriber is None:
            return
        while True:
            try:
                subscriber.put_nowait(item)  # type: ignore[arg-type]
                return
            except Full:
                try:
                    subscriber.get_nowait()
                except Exception:
                    return

    async def close(self) -> None:
        if self._enabled or self._owner_reserved:
            await self.disable()
        if self._started:
            self._queue_private(self._stop_sentinel)
            if self._consumer_task is not None:
                await self._consumer_task
            if self._subscriber is not None:
                self._bus.unsubscribe(self._subscriber)
        self._subscriber = None
        self._consumer_task = None
        self._started = False
        self._freshness_deadline_ns = None
        self._causal_after_ns = None
        self._last_post_ack_cycle = None
        self._settling_pending = False
        self._resolution_limit_direction = None

    def _freshness_ns(self) -> int:
        assert self._settings is not None
        source = self._source_config(self._settings.source_id)
        assert source is not None
        return int(2.0 * float(source.poll_interval_s) * 1_000_000_000)

    def _arm_after_ack(self) -> None:
        now = self._monotonic_ns()
        self._causal_after_ns = now
        self._settling_pending = True
        self._last_post_ack_cycle = None
        self._freshness_deadline_ns = now + self._freshness_ns()
        self._state = ZeroExportControllerState.WAITING_FOR_SAMPLE

    @staticmethod
    def _safe_off_ack(status: ManualPwmStatus) -> bool:
        return bool(
            status.ack_result == "APPLIED"
            and status.requested_duty_percent == 0.0
            and status.actual_duty_percent == 0.0
            and status.compare_ticks == 0
            and status.node_id is not None
            and status.boot_id is not None
            and status.command_sequence is not None
        )

    def _same_pinned_actuator(self, status: ManualPwmStatus) -> tuple[bool, str | None]:
        if status.node_id is None or status.boot_id is None or status.state is ManualPwmState.DISCONNECTED:
            return False, "ACTUATOR_DISCONNECTED"
        if self._actuator_node_id is not None and status.node_id != self._actuator_node_id:
            return False, "ACTUATOR_NODE_CHANGED"
        if self._actuator_boot_id is not None and status.boot_id != self._actuator_boot_id:
            return False, "ACTUATOR_BOOT_CHANGED"
        if status.state is ManualPwmState.UNSUPPORTED:
            return False, "PWM_DUTY_CONTROL_NOT_SUPPORTED"
        return True, None

    @staticmethod
    def _qualified_command_ack(status: ManualPwmStatus, requested: float) -> bool:
        actual = _finite(status.actual_duty_percent)
        return bool(
            status.ack_result == "APPLIED"
            and status.node_id is not None
            and status.boot_id is not None
            and status.command_sequence is not None
            and status.requested_duty_percent == requested
            and actual is not None
            and ((requested == 0.0 and actual == 0.0 and status.compare_ticks == 0)
                 or (requested > 0.0 and actual > 0.0 and status.compare_ticks is not None and status.compare_ticks > 0))
        )

    @staticmethod
    def _same_physical_pwm_state(before: ManualPwmStatus, after: ManualPwmStatus) -> bool:
        before_actual = _finite(before.actual_duty_percent)
        after_actual = _finite(after.actual_duty_percent)
        return bool(
            before.compare_ticks is not None
            and after.compare_ticks is not None
            and before.compare_ticks > 0
            and after.compare_ticks > 0
            and before.compare_ticks == after.compare_ticks
            and before.period_ticks is not None
            and after.period_ticks is not None
            and before.period_ticks > 0
            and before.period_ticks == after.period_ticks
            and before_actual is not None
            and after_actual is not None
            and math.isclose(before_actual, after_actual, rel_tol=0.0, abs_tol=1e-12)
        )

    def _apply_ack_evidence(self, status: ManualPwmStatus) -> None:
        self._actuator_node_id = status.node_id
        self._actuator_boot_id = status.boot_id
        self._command_sequence = status.command_sequence
        self._confirmed_requested_duty = _finite(status.requested_duty_percent)
        self._confirmed_actual_duty = _finite(status.actual_duty_percent)
        self._confirmed_compare_ticks = status.compare_ticks
        self._confirmed_period_ticks = status.period_ticks

    async def enable(self) -> ZeroExportControllerStatus:
        async with self._operation_lock:
            if not self._started:
                raise Stage4CZeroExportControllerError("ZERO_EXPORT_NOT_STARTED")
            if self._enabled or self._owner_reserved:
                raise Stage4CZeroExportControllerError("ZERO_EXPORT_ACTIVE")
            if self._settings is None:
                raise Stage4CZeroExportControllerError("ZERO_EXPORT_NOT_CONFIGURED")
            if self._source_config(self._settings.source_id) is None:
                raise Stage4CZeroExportControllerError("SOURCE_NOT_AVAILABLE")

            self._state = ZeroExportControllerState.ENABLING
            self._reason = None
            self._safe_confirmed = None
            self._action = None
            self._lower_bracket = None
            self._upper_bracket = None
            self._sample_cycle_id = None
            self._measured_p_w = None
            self._sample_quality = None
            self._confirmed_compare_ticks = None
            self._confirmed_period_ticks = None
            self._resolution_limit_direction = None
            try:
                self._manual_pwm.reserve_pwm_owner(ZERO_EXPORT_PWM_OWNER)
                self._owner_reserved = True
                status = await self._manual_pwm.run_reserved_pwm(
                    0.0,
                    owner=ZERO_EXPORT_PWM_OWNER,
                )
            except Stage3AError as exc:
                self._release_owner_best_effort()
                self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
                self._reason = str(exc)
                self._safe_confirmed = False
                raise Stage4CZeroExportControllerError(str(exc)) from exc
            except Exception as exc:
                self._release_owner_best_effort()
                self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
                self._reason = "SAFE_OFF_UNCONFIRMED"
                self._safe_confirmed = False
                raise Stage4CZeroExportControllerError("SAFE_OFF_UNCONFIRMED") from exc

            if not self._safe_off_ack(status):
                self._release_owner_best_effort()
                self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
                self._reason = "SAFE_OFF_UNCONFIRMED"
                self._safe_confirmed = False
                raise Stage4CZeroExportControllerError("SAFE_OFF_UNCONFIRMED")

            self._apply_ack_evidence(status)
            self._safe_confirmed = True
            self._enabled = True
            self._arm_after_ack()
            self._diagnostic_log.append(
                "ZERO_EXPORT_ENABLED",
                source_id=self._settings.source_id,
                phase=self._settings.phase,
                p_deadband_w=self._settings.p_deadband_w,
                node_id=self._actuator_node_id,
                boot_id=self._actuator_boot_id,
                sequence=self._command_sequence,
            )
            return self.status()

    def _release_owner_best_effort(self) -> None:
        if not self._owner_reserved:
            return
        try:
            self._manual_pwm.release_pwm_owner(ZERO_EXPORT_PWM_OWNER)
        except Exception:
            pass
        self._owner_reserved = False

    async def _finish_safe(self, *, reason: str, blocked_state: ZeroExportControllerState) -> None:
        current = self._manual_pwm.manual_pwm_status()
        same, actuator_reason = self._same_pinned_actuator(current)
        self._resolution_limit_direction = None
        if not same:
            self._enabled = False
            self._safe_confirmed = False
            self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
            self._reason = actuator_reason or reason
            self._freshness_deadline_ns = None
            self._release_owner_best_effort()
            self._diagnostic_log.append(
                "ZERO_EXPORT_SAFE_BLOCK",
                reason=self._reason,
                state=self._state.value,
                safe_confirmed=False,
            )
            return

        safe = False
        try:
            status = await self._manual_pwm.run_reserved_pwm(
                0.0,
                owner=ZERO_EXPORT_PWM_OWNER,
            )
            safe = self._safe_off_ack(status)
            if safe:
                self._apply_ack_evidence(status)
        except Exception:
            safe = False

        self._enabled = False
        self._freshness_deadline_ns = None
        self._safe_confirmed = safe
        self._release_owner_best_effort()
        if safe:
            self._state = blocked_state
            self._reason = reason
        else:
            self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
            self._reason = "SAFE_OFF_UNCONFIRMED"
        self._diagnostic_log.append(
            "ZERO_EXPORT_SAFE_BLOCK",
            reason=self._reason,
            state=self._state.value,
            safe_confirmed=self._safe_confirmed,
            node_id=self._actuator_node_id,
            boot_id=self._actuator_boot_id,
            sequence=self._command_sequence,
        )

    async def disable(self) -> ZeroExportControllerStatus:
        async with self._operation_lock:
            if self._state is ZeroExportControllerState.DISABLED and not self._owner_reserved:
                return self.status()

            if self._state is ZeroExportControllerState.SAFE_UNCONFIRMED and not self._owner_reserved:
                status = self._manual_pwm.manual_pwm_status()
                if self._safe_off_ack(status):
                    self._apply_ack_evidence(status)
                    self._safe_confirmed = True
                    self._state = ZeroExportControllerState.DISABLED
                    self._reason = None
                return self.status()

            if self._owner_reserved:
                current = self._manual_pwm.manual_pwm_status()
                same, actuator_reason = self._same_pinned_actuator(current)
                if not same:
                    self._enabled = False
                    self._safe_confirmed = False
                    self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
                    self._reason = actuator_reason
                    self._release_owner_best_effort()
                    return self.status()
                try:
                    status = await self._manual_pwm.run_reserved_pwm(
                        0.0,
                        owner=ZERO_EXPORT_PWM_OWNER,
                    )
                except Exception:
                    status = current
                if not self._safe_off_ack(status):
                    self._enabled = False
                    self._safe_confirmed = False
                    self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
                    self._reason = "SAFE_OFF_UNCONFIRMED"
                    self._release_owner_best_effort()
                    return self.status()
                self._apply_ack_evidence(status)

            self._enabled = False
            self._safe_confirmed = True
            self._state = ZeroExportControllerState.DISABLED
            self._reason = None
            self._freshness_deadline_ns = None
            self._causal_after_ns = None
            self._last_post_ack_cycle = None
            self._settling_pending = False
            self._resolution_limit_direction = None
            self._release_owner_best_effort()
            self._diagnostic_log.append(
                "ZERO_EXPORT_DISABLED",
                safe_confirmed=True,
                node_id=self._actuator_node_id,
                boot_id=self._actuator_boot_id,
                sequence=self._command_sequence,
            )
            return self.status()

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
                async with self._operation_lock:
                    if self._enabled and self._freshness_deadline_ns is not None:
                        if self._monotonic_ns() > self._freshness_deadline_ns:
                            await self._finish_safe(
                                reason="SAMPLE_STALE",
                                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
                            )
                continue
            if item is self._stop_sentinel:
                return
            async with self._operation_lock:
                if not self._enabled or self._settings is None:
                    continue
                await self._handle_event(item)

    async def _handle_event(self, event: RuntimeEvent) -> None:
        assert self._settings is not None
        if isinstance(event, DiagnosticEvent):
            if (
                event.device_id == self._settings.source_id
                and event.event.startswith(_ACQUISITION_EVENT_PREFIX)
            ):
                await self._finish_safe(
                    reason="ACQUISITION_FAILURE",
                    blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
                )
            return

        sample = event
        if sample.identity.device_id != self._settings.source_id:
            return

        current = self._manual_pwm.manual_pwm_status()
        same, actuator_reason = self._same_pinned_actuator(current)
        if not same:
            self._enabled = False
            self._safe_confirmed = False
            self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
            self._reason = actuator_reason
            self._freshness_deadline_ns = None
            self._resolution_limit_direction = None
            self._release_owner_best_effort()
            return

        causal_after = self._causal_after_ns
        if causal_after is not None and sample.timing.cycle_finished_monotonic_ns <= causal_after:
            return

        now = self._monotonic_ns()
        age_ns = now - sample.timing.cycle_finished_monotonic_ns
        if age_ns < 0 or age_ns > self._freshness_ns():
            await self._finish_safe(
                reason="SAMPLE_STALE",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return
        if sample.quality is not SampleQuality.VALID:
            await self._finish_safe(
                reason="SAMPLE_INVALID",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return

        cycle = sample.identity.cycle_id
        if self._last_post_ack_cycle is not None and cycle != self._last_post_ack_cycle + 1:
            await self._finish_safe(
                reason="SAMPLE_SEQUENCE_GAP",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return
        self._last_post_ack_cycle = cycle
        self._freshness_deadline_ns = now + self._freshness_ns()

        if self._settling_pending:
            self._settling_pending = False
            self._state = ZeroExportControllerState.SETTLING
            return

        measured_p = self._selected_p(sample)
        if measured_p is None:
            await self._finish_safe(
                reason="SAMPLE_INVALID",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return
        if self._confirmed_requested_duty is None:
            await self._finish_safe(
                reason="CONFIRMED_DUTY_UNKNOWN",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return

        self._sample_cycle_id = cycle
        self._measured_p_w = measured_p
        self._sample_quality = sample.quality.value

        if self._resolution_limit_direction is not None:
            same_direction = bool(
                (self._resolution_limit_direction is ZeroExportAction.INCREASE
                 and measured_p < -self._settings.p_deadband_w)
                or
                (self._resolution_limit_direction is ZeroExportAction.DECREASE
                 and measured_p > self._settings.p_deadband_w)
            )
            if same_direction:
                if self._state is not ZeroExportControllerState.RESOLUTION_LIMIT:
                    self._diagnostic_log.append(
                        "ZERO_EXPORT_RESOLUTION_LIMIT",
                        cycle_id=cycle,
                        measured_p_w=measured_p,
                        direction=self._resolution_limit_direction.value,
                        requested_duty_percent=self._confirmed_requested_duty,
                        actual_duty_percent=self._confirmed_actual_duty,
                        compare_ticks=self._confirmed_compare_ticks,
                        period_ticks=self._confirmed_period_ticks,
                    )
                self._action = ZeroExportAction.RESOLUTION_LIMIT
                self._state = ZeroExportControllerState.RESOLUTION_LIMIT
                self._reason = "PWM_RESOLUTION_LIMIT"
                return
            self._resolution_limit_direction = None
            self._reason = None

        decision = calculate_zero_export_step(
            measured_p_w=measured_p,
            p_deadband_w=self._settings.p_deadband_w,
            confirmed_duty_percent=self._confirmed_requested_duty,
            lower_bracket_duty_percent=self._lower_bracket,
            upper_bracket_duty_percent=self._upper_bracket,
        )
        self._action = decision.action
        self._lower_bracket = decision.lower_bracket_duty_percent
        self._upper_bracket = decision.upper_bracket_duty_percent
        self._reason = (
            "LOW_AUTHORITY_LIMIT"
            if decision.action is ZeroExportAction.LIMIT_LOW
            else None
        )
        self._diagnostic_log.append(
            "ZERO_EXPORT_DECISION",
            cycle_id=cycle,
            measured_p_w=measured_p,
            action=decision.action.value,
            confirmed_requested_duty_percent=self._confirmed_requested_duty,
            next_requested_duty_percent=decision.next_duty_percent,
            lower_bracket_duty_percent=self._lower_bracket,
            upper_bracket_duty_percent=self._upper_bracket,
        )

        if decision.next_duty_percent == self._confirmed_requested_duty:
            if decision.action is ZeroExportAction.HOLD:
                self._state = ZeroExportControllerState.TARGET_BAND
            elif decision.action is ZeroExportAction.LIMIT_LOW:
                if self._state is not ZeroExportControllerState.LIMIT_LOW:
                    self._diagnostic_log.append(
                        "ZERO_EXPORT_LIMIT_LOW",
                        cycle_id=cycle,
                        measured_p_w=measured_p,
                        confirmed_requested_duty_percent=self._confirmed_requested_duty,
                        upper_bracket_duty_percent=self._upper_bracket,
                        safe_confirmed=self._safe_confirmed,
                    )
                self._state = ZeroExportControllerState.LIMIT_LOW
            elif decision.action is ZeroExportAction.LIMIT_HIGH:
                self._state = ZeroExportControllerState.LIMIT_HIGH
            elif decision.action is ZeroExportAction.SAFE_OFF:
                self._state = ZeroExportControllerState.SAFE_OFF
            else:
                self._state = ZeroExportControllerState.CONTROLLING
            return

        self._state = ZeroExportControllerState.CONTROLLING
        requested = decision.next_duty_percent
        before_status = current
        try:
            status = await self._manual_pwm.run_reserved_pwm(
                requested,
                owner=ZERO_EXPORT_PWM_OWNER,
            )
        except Exception:
            await self._finish_safe(
                reason="PWM_COMMAND_NOT_CONFIRMED",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return

        same, actuator_reason = self._same_pinned_actuator(status)
        if not same:
            self._enabled = False
            self._safe_confirmed = False
            self._state = ZeroExportControllerState.SAFE_UNCONFIRMED
            self._reason = actuator_reason
            self._freshness_deadline_ns = None
            self._resolution_limit_direction = None
            self._release_owner_best_effort()
            return
        if not self._qualified_command_ack(status, requested):
            await self._finish_safe(
                reason="PWM_COMMAND_NOT_CONFIRMED",
                blocked_state=ZeroExportControllerState.BLOCKED_SAFE,
            )
            return

        physical_unchanged = bool(
            requested != self._confirmed_requested_duty
            and requested > 0.0
            and self._same_physical_pwm_state(before_status, status)
        )
        self._apply_ack_evidence(status)
        self._safe_confirmed = (requested == 0.0)

        if physical_unchanged and decision.action in {ZeroExportAction.INCREASE, ZeroExportAction.DECREASE}:
            self._resolution_limit_direction = decision.action
            self._action = ZeroExportAction.RESOLUTION_LIMIT
            self._reason = "PWM_RESOLUTION_LIMIT"
            self._arm_after_ack()
            self._state = ZeroExportControllerState.RESOLUTION_LIMIT
            self._diagnostic_log.append(
                "ZERO_EXPORT_RESOLUTION_LIMIT",
                cycle_id=cycle,
                measured_p_w=measured_p,
                direction=decision.action.value,
                requested_duty_percent=self._confirmed_requested_duty,
                actual_duty_percent=self._confirmed_actual_duty,
                compare_ticks=self._confirmed_compare_ticks,
                period_ticks=self._confirmed_period_ticks,
            )
            return

        self._resolution_limit_direction = None
        if decision.action is ZeroExportAction.LIMIT_LOW:
            self._diagnostic_log.append(
                "ZERO_EXPORT_LIMIT_LOW",
                cycle_id=cycle,
                measured_p_w=measured_p,
                confirmed_requested_duty_percent=self._confirmed_requested_duty,
                upper_bracket_duty_percent=self._upper_bracket,
                safe_confirmed=self._safe_confirmed,
            )
        self._arm_after_ack()

    def _selected_p(self, sample: MeasurementSample) -> float | None:
        assert self._settings is not None
        if self._settings.phase == "A":
            value = sample.phase_a.measurement.p
        elif self._settings.phase == "B":
            value = sample.phase_b.measurement.p
        else:
            value = sample.phase_c.measurement.p
        return _finite(value)
