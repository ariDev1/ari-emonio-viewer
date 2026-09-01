from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent

from .controller import ThreePhaseControlResult, calculate_three_phase_request
from .model import (
    ControlMode,
    LoadControlTiming,
    PersistentLoadControlConfig,
    SafeState,
    SessionState,
    ThreePhasePower,
)
from .protocol import AckFrame, CommandFrame, HelloFrame, LOAD_CONTROL_PROTOCOL_VERSION
from .state_machine import ControlStateMachine, TripReason


class EnableRejected(RuntimeError):
    """Raised when the complete external-control enable gate does not pass."""


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    command: CommandFrame | None = None
    event: str | None = None
    reason: str | None = None
    calculation: ThreePhaseControlResult | None = None


@dataclass(slots=True)
class _OutstandingCommand:
    command: CommandFrame
    kind: Literal["NORMAL", "SAFE"]
    sent_monotonic_ns: int


class LoadControlSupervisor:
    """Deterministic supervisory state built only from canonical runtime evidence."""

    def __init__(
        self,
        config: PersistentLoadControlConfig,
        timing: LoadControlTiming,
        *,
        viewer_session_id: str,
    ) -> None:
        if not isinstance(viewer_session_id, str) or not viewer_session_id:
            raise ValueError("viewer_session_id must be non-empty text")
        self.config = config
        self.timing = timing
        self.viewer_session_id = viewer_session_id
        self._state = ControlStateMachine()
        self.session_state = SessionState.UNBOUND if config.bound_actuator_node_id is None else SessionState.UNAVAILABLE
        self._hello: HelloFrame | None = None
        self._last_sample: MeasurementSample | None = None
        self.last_source_cycle_id: int | None = None
        self._last_sample_age_s: float | None = None
        self.acknowledged_p: ThreePhasePower | None = None
        self._outstanding: _OutstandingCommand | None = None
        self._obsolete_sequences: set[int] = set()
        self._next_sequence = 1
        self._eligible_after_cycle_id: int | None = None

    @property
    def control_mode(self) -> ControlMode:
        return self._state.mode

    @property
    def safe_state(self) -> SafeState:
        return self._state.safe_state

    @property
    def trip_reason(self) -> str | None:
        return None if self._state.trip_reason is None else self._state.trip_reason.value

    @property
    def outstanding_command(self) -> CommandFrame | None:
        return None if self._outstanding is None else self._outstanding.command

    @property
    def actuator_boot_id(self) -> str | None:
        return None if self._hello is None else self._hello.boot_id

    @property
    def last_sample_age_s(self) -> float | None:
        return self._last_sample_age_s

    def _age_s(self, sample: MeasurementSample, now_monotonic_ns: int) -> float:
        age_ns = now_monotonic_ns - sample.timing.cycle_finished_monotonic_ns
        if age_ns < 0:
            return float("inf")
        return age_ns / 1_000_000_000.0

    def _phase_p(self, sample: MeasurementSample) -> ThreePhasePower:
        return ThreePhasePower(
            sample.phase_a.measurement.p,
            sample.phase_b.measurement.p,
            sample.phase_c.measurement.p,
        )

    def _phase_q(self, sample: MeasurementSample) -> ThreePhasePower:
        return ThreePhasePower(
            sample.phase_a.measurement.q,
            sample.phase_b.measurement.q,
            sample.phase_c.measurement.q,
        )

    def _effective_limits(self) -> ThreePhasePower:
        if self._hello is None:
            raise RuntimeError("actuator session is not qualified")
        limits = (self.config.operator_limit_a, self.config.operator_limit_b, self.config.operator_limit_c)
        if any(value is None for value in limits):
            raise RuntimeError("operator limits are not configured")
        return ThreePhasePower(
            min(self._hello.p_max.a, float(limits[0])),
            min(self._hello.p_max.b, float(limits[1])),
            min(self._hello.p_max.c, float(limits[2])),
        )

    def _allocate_command(
        self,
        *,
        sample: MeasurementSample,
        request: ThreePhasePower,
        control_enabled: bool,
        now_utc: datetime,
        now_monotonic_ns: int,
        kind: Literal["NORMAL", "SAFE"],
    ) -> CommandFrame:
        if self._hello is None:
            raise RuntimeError("actuator session is not qualified")
        sequence = self._next_sequence
        self._next_sequence += 1
        command = CommandFrame(
            protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
            viewer_session_id=self.viewer_session_id,
            node_id=self._hello.node_id,
            boot_id=self._hello.boot_id,
            sequence=sequence,
            emonio_device_id=sample.identity.device_id,
            measurement_cycle_id=sample.identity.cycle_id,
            measurement_utc=sample.timing.cycle_finished_utc.isoformat(),
            command_utc=now_utc.isoformat(),
            control_enabled=control_enabled,
            p_reserve=0.0 if self.config.p_reserve is None else self.config.p_reserve,
            measured_p=self._phase_p(sample),
            measured_q=self._phase_q(sample),
            p_load_request=request,
            q_comp_request=ThreePhasePower(0.0, 0.0, 0.0),
        )
        self._outstanding = _OutstandingCommand(command, kind, now_monotonic_ns)
        return command

    def _safe_command(self, *, now_utc: datetime, now_monotonic_ns: int) -> CommandFrame | None:
        if self.session_state is not SessionState.READY or self._hello is None or self._last_sample is None:
            self._state.mark_safe_unconfirmed()
            return None
        if self._outstanding is not None:
            if self._outstanding.kind == "SAFE":
                return self._outstanding.command
            self._obsolete_sequences.add(self._outstanding.command.sequence)
            self._outstanding = None
        self._state.mark_safe_unconfirmed()
        return self._allocate_command(
            sample=self._last_sample,
            request=ThreePhasePower(0.0, 0.0, 0.0),
            control_enabled=False,
            now_utc=now_utc,
            now_monotonic_ns=now_monotonic_ns,
            kind="SAFE",
        )

    def _trip_with_safe(
        self,
        reason: TripReason,
        *,
        now_utc: datetime,
        now_monotonic_ns: int,
    ) -> SupervisorDecision:
        self._state.trip(reason)
        return SupervisorDecision(
            command=self._safe_command(now_utc=now_utc, now_monotonic_ns=now_monotonic_ns),
            event="CONTROL_TRIPPED",
            reason=reason.value,
        )

    def qualify_session(self, hello: HelloFrame, *, now_monotonic_ns: int) -> SupervisorDecision:
        bound = self.config.bound_actuator_node_id
        if bound is None:
            self.session_state = SessionState.UNBOUND
            return SupervisorDecision(event="ACTUATOR_HELLO_REJECTED", reason="ACTUATOR_UNBOUND")
        if hello.node_id != bound:
            self.session_state = SessionState.SESSION_FAULT
            if self.control_mode is ControlMode.ENABLED:
                self._state.trip(TripReason.ACTUATOR_IDENTITY_MISMATCH)
            return SupervisorDecision(event="ACTUATOR_HELLO_REJECTED", reason="ACTUATOR_IDENTITY_MISMATCH")
        if "ACTIVE_LOAD_CONTROL" not in hello.capabilities:
            self.session_state = SessionState.SESSION_FAULT
            if self.control_mode is ControlMode.ENABLED:
                self._state.trip(TripReason.CAPABILITY_CHANGED)
            return SupervisorDecision(event="ACTUATOR_HELLO_REJECTED", reason="ACTIVE_LOAD_CONTROL_MISSING")

        previous_boot = None if self._hello is None else self._hello.boot_id
        self._hello = hello
        self.session_state = SessionState.READY
        if previous_boot is not None and previous_boot != hello.boot_id:
            self.acknowledged_p = None
            self._outstanding = None
            self._obsolete_sequences.clear()
            self._state.mark_safe_unconfirmed()
            if self.control_mode is ControlMode.ENABLED:
                self._state.trip(TripReason.ACTUATOR_BOOT_CHANGED)
                return SupervisorDecision(event="CONTROL_TRIPPED", reason="ACTUATOR_BOOT_CHANGED")
        return SupervisorDecision(event="ACTUATOR_HELLO_ACCEPTED")

    def enable(self, *, evidence_healthy: bool, now_monotonic_ns: int) -> None:
        if self.config.bound_emonio_device_id is None:
            raise EnableRejected("SOURCE_UNBOUND")
        if self.config.bound_actuator_node_id is None:
            raise EnableRejected("ACTUATOR_UNBOUND")
        if self.config.p_reserve is None:
            raise EnableRejected("P_RESERVE_NOT_CONFIGURED")
        if any(value is None for value in (self.config.operator_limit_a, self.config.operator_limit_b, self.config.operator_limit_c)):
            raise EnableRejected("OPERATOR_LIMIT_NOT_CONFIGURED")
        if self.session_state is not SessionState.READY or self._hello is None:
            raise EnableRejected("ACTUATOR_NOT_READY")
        if not evidence_healthy:
            raise EnableRejected("EVIDENCE_UNHEALTHY")
        if self._last_sample is None:
            raise EnableRejected("NO_SAMPLE")
        if self._last_sample.quality is not SampleQuality.VALID:
            raise EnableRejected("SAMPLE_NOT_VALID")
        age = self._age_s(self._last_sample, now_monotonic_ns)
        self._last_sample_age_s = age
        if age > self.timing.control_sample_max_age_s:
            raise EnableRejected("SAMPLE_STALE")
        if self.safe_state is not SafeState.SAFE_CONFIRMED:
            raise EnableRejected("SAFE_NOT_CONFIRMED")
        if self.acknowledged_p is None:
            raise EnableRejected("ACTUATOR_STATE_NOT_CONFIRMED")
        if self._outstanding is not None:
            raise EnableRejected("COMMAND_OUTSTANDING")
        self._state.enable()
        self._eligible_after_cycle_id = self.last_source_cycle_id

    def disable(self, *, now_utc: datetime, now_monotonic_ns: int) -> SupervisorDecision:
        was_tripped = self.control_mode is ControlMode.TRIPPED
        self._state.disable()
        command = self._safe_command(now_utc=now_utc, now_monotonic_ns=now_monotonic_ns)
        return SupervisorDecision(
            command=command,
            event="CONTROL_SAFE_REASSERTED" if was_tripped else "CONTROL_DISABLED",
        )

    def observe_sample(
        self,
        sample: MeasurementSample,
        *,
        now_monotonic_ns: int,
        now_utc: datetime,
    ) -> SupervisorDecision:
        if sample.identity.device_id != self.config.bound_emonio_device_id:
            return SupervisorDecision(event="CONTROL_SAMPLE_IGNORED", reason="SOURCE_NOT_BOUND")

        cycle_id = sample.identity.cycle_id
        if self.last_source_cycle_id is not None and cycle_id != self.last_source_cycle_id + 1:
            self.last_source_cycle_id = cycle_id
            self._last_sample = sample
            self._last_sample_age_s = self._age_s(sample, now_monotonic_ns)
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.CONTROL_SAMPLE_SEQUENCE_GAP,
                    now_utc=now_utc,
                    now_monotonic_ns=now_monotonic_ns,
                )
            return SupervisorDecision(event="CONTROL_SAMPLE_SEQUENCE_GAP")

        self.last_source_cycle_id = cycle_id
        self._last_sample = sample
        age = self._age_s(sample, now_monotonic_ns)
        self._last_sample_age_s = age

        if sample.quality is not SampleQuality.VALID:
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.MEASUREMENT_NOT_VALID,
                    now_utc=now_utc,
                    now_monotonic_ns=now_monotonic_ns,
                )
            return SupervisorDecision(event="CONTROL_SAMPLE_NOT_VALID", reason=sample.quality.value)

        if age > self.timing.control_sample_max_age_s:
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.CONTROL_SAMPLE_STALE,
                    now_utc=now_utc,
                    now_monotonic_ns=now_monotonic_ns,
                )
            return SupervisorDecision(event="CONTROL_SAMPLE_STALE")

        if self.control_mode is not ControlMode.ENABLED:
            if self.safe_state is SafeState.SAFE_UNCONFIRMED and self._outstanding is None:
                safe = self._safe_command(now_utc=now_utc, now_monotonic_ns=now_monotonic_ns)
                if safe is not None:
                    return SupervisorDecision(command=safe, event="SAFE_COMMAND_REQUESTED")
            return SupervisorDecision(event="CONTROL_SAMPLE_OBSERVED")

        if self._outstanding is not None:
            return SupervisorDecision(event="CONTROL_SAMPLE_OBSERVED_WAITING_FOR_ACK")
        if self._eligible_after_cycle_id is not None and cycle_id <= self._eligible_after_cycle_id:
            return SupervisorDecision(event="CONTROL_SAMPLE_OBSERVED_NOT_NEW")
        if self.acknowledged_p is None or self.config.p_reserve is None:
            return self._trip_with_safe(
                TripReason.ACK_INVALID,
                now_utc=now_utc,
                now_monotonic_ns=now_monotonic_ns,
            )

        calculation = calculate_three_phase_request(
            measured_p=self._phase_p(sample),
            p_reserve=self.config.p_reserve,
            acknowledged_p=self.acknowledged_p,
            p_limit=self._effective_limits(),
        )
        request = ThreePhasePower(
            calculation.a.limited_request,
            calculation.b.limited_request,
            calculation.c.limited_request,
        )
        command = self._allocate_command(
            sample=sample,
            request=request,
            control_enabled=True,
            now_utc=now_utc,
            now_monotonic_ns=now_monotonic_ns,
            kind="NORMAL",
        )
        return SupervisorDecision(command=command, event="CONTROL_COMMAND_CALCULATED", calculation=calculation)

    def observe_diagnostic(self, event: DiagnosticEvent, *, now_utc: datetime) -> SupervisorDecision:
        if event.device_id != self.config.bound_emonio_device_id:
            return SupervisorDecision(event="CONTROL_DIAGNOSTIC_IGNORED", reason="SOURCE_NOT_BOUND")
        if self.last_source_cycle_id is not None and event.cycle_id != self.last_source_cycle_id + 1:
            self.last_source_cycle_id = event.cycle_id
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.CONTROL_SAMPLE_SEQUENCE_GAP,
                    now_utc=now_utc,
                    now_monotonic_ns=0 if self._last_sample is None else self._last_sample.timing.cycle_finished_monotonic_ns,
                )
        else:
            self.last_source_cycle_id = event.cycle_id
        if event.event.startswith("ACQUISITION_") and self.control_mode is ControlMode.ENABLED:
            return self._trip_with_safe(
                TripReason.ACQUISITION_FAILURE,
                now_utc=now_utc,
                now_monotonic_ns=0 if self._last_sample is None else self._last_sample.timing.cycle_finished_monotonic_ns,
            )
        return SupervisorDecision(event="CONTROL_DIAGNOSTIC_OBSERVED")

    def _ack_matches(self, ack: AckFrame, expected: CommandFrame) -> bool:
        if self._hello is None:
            return False
        if (
            ack.protocol_version != LOAD_CONTROL_PROTOCOL_VERSION
            or ack.viewer_session_id != self.viewer_session_id
            or ack.node_id != self._hello.node_id
            or ack.boot_id != self._hello.boot_id
            or ack.sequence != expected.sequence
            or ack.result != "APPLIED"
        ):
            return False
        limits = self._effective_limits()
        return (
            0.0 <= ack.applied_p.a <= limits.a
            and 0.0 <= ack.applied_p.b <= limits.b
            and 0.0 <= ack.applied_p.c <= limits.c
        )

    def accept_ack(self, ack: AckFrame, *, now_monotonic_ns: int) -> SupervisorDecision:
        if ack.sequence in self._obsolete_sequences:
            return SupervisorDecision(event="CONTROL_ACK_OBSOLETE")
        if self._outstanding is None:
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.ACK_INVALID,
                    now_utc=self._last_sample.timing.cycle_finished_utc if self._last_sample is not None else datetime.fromisoformat(ack.ack_utc),
                    now_monotonic_ns=now_monotonic_ns,
                )
            return SupervisorDecision(event="CONTROL_ACK_REJECTED", reason="NO_COMMAND_OUTSTANDING")

        outstanding = self._outstanding
        if not self._ack_matches(ack, outstanding.command):
            if self.control_mode is ControlMode.ENABLED:
                return self._trip_with_safe(
                    TripReason.ACK_INVALID,
                    now_utc=datetime.fromisoformat(ack.ack_utc),
                    now_monotonic_ns=now_monotonic_ns,
                )
            return SupervisorDecision(event="CONTROL_ACK_REJECTED", reason="ACK_IDENTITY_OR_VALUE_INVALID")

        if outstanding.kind == "SAFE" and ack.applied_p != ThreePhasePower(0.0, 0.0, 0.0):
            return SupervisorDecision(event="CONTROL_ACK_REJECTED", reason="SAFE_NOT_APPLIED")

        self._outstanding = None
        self.acknowledged_p = ack.applied_p
        if outstanding.kind == "SAFE":
            self._state.mark_safe_confirmed()
            return SupervisorDecision(event="SAFE_STATE_CONFIRMED")
        self._eligible_after_cycle_id = self.last_source_cycle_id
        return SupervisorDecision(event="CONTROL_ACK_ACCEPTED")

    def check_ack_timeout(self, *, now_monotonic_ns: int, now_utc: datetime) -> SupervisorDecision:
        if self._outstanding is None:
            return SupervisorDecision()
        age_s = (now_monotonic_ns - self._outstanding.sent_monotonic_ns) / 1_000_000_000.0
        if age_s <= self.timing.ack_timeout_s:
            return SupervisorDecision()
        if self.control_mode is ControlMode.ENABLED:
            return self._trip_with_safe(
                TripReason.ACK_TIMEOUT,
                now_utc=now_utc,
                now_monotonic_ns=now_monotonic_ns,
            )
        self._state.mark_safe_unconfirmed()
        return SupervisorDecision(event="SAFE_ACK_TIMEOUT", reason="ACK_TIMEOUT")

    def session_lost(self) -> SupervisorDecision:
        self.session_state = SessionState.UNAVAILABLE
        self._hello = None
        self._outstanding = None
        self.acknowledged_p = None
        self._state.mark_safe_unconfirmed()
        if self.control_mode is ControlMode.ENABLED:
            self._state.trip(TripReason.ACTUATOR_CONNECTION_LOST)
            return SupervisorDecision(event="CONTROL_TRIPPED", reason="ACTUATOR_CONNECTION_LOST")
        return SupervisorDecision(event="ACTUATOR_CONNECTION_LOST")
