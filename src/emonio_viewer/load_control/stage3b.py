from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from .model import ThreePhasePower
from .protocol import (
    AckFrame,
    CommandFrame,
    LOAD_CONTROL_PROTOCOL_VERSION,
    ProtocolError,
    StatusFrame,
)
from .qualified_channel import QualifiedActuatorChannelError
from .stage3a import (
    ACK_TIMEOUT_S,
    ZERO_POWER,
    Stage3AError,
    Stage3ASafeCommandService,
    Stage3AState,
    Stage3AStatus,
    _ActuatorDisconnected,
    _SourceAcquisitionFailure,
    _aware_iso,
    _error_text,
    _valid_poll_interval,
)


SIMULATED_TEST_POWER = ThreePhasePower(1.0, 0.0, 0.0)
SIMULATED_TEST_P_RESERVE_W = 1.0


class Stage3BState(str, Enum):
    RESET_REQUIRED = "RESET_REQUIRED"


@dataclass(frozen=True, slots=True)
class Stage3BStatus:
    state: Stage3AState | Stage3BState
    selected_source_id: str | None
    sample_cycle_id: int | None
    command_sequence: int | None
    ack_result: str | None
    rejection_reason: str | None
    admissible: bool
    safe_reset_required: bool
    fixed_request: ThreePhasePower


class Stage3BExplicitCommandService(Stage3ASafeCommandService):
    """Add one fixed nonzero simulated COMMAND to the Stage-3A exchange owner.

    The service keeps the Stage-3A zero-output path unchanged. The Stage-3B
    request is fixed at 1 W on phase A and 0 W on phases B/C. Canonical Emonio
    P/Q values are provenance only. They do not calculate the request.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._safe_reset_required = False

    def simulated_status(self) -> Stage3BStatus:
        safe_status = super().status()
        state: Stage3AState | Stage3BState = safe_status.state
        if self._safe_reset_required and not self._active:
            state = Stage3BState.RESET_REQUIRED
        return Stage3BStatus(
            state=state,
            selected_source_id=safe_status.selected_source_id,
            sample_cycle_id=safe_status.sample_cycle_id,
            command_sequence=safe_status.command_sequence,
            ack_result=safe_status.ack_result,
            rejection_reason=safe_status.rejection_reason,
            admissible=safe_status.admissible and not self._safe_reset_required,
            safe_reset_required=self._safe_reset_required,
            fixed_request=SIMULATED_TEST_POWER,
        )

    async def run_safe_test(self) -> Stage3AStatus:
        status = await super().run_safe_test()
        if status.state is Stage3AState.PASSED and self._safe_reset_required:
            self._safe_reset_required = False
            self._diagnostic_log.append(
                "SIMULATED_ZERO_RESET_CONFIRMED",
                emonio_device_id=self._selected_source_id,
                sequence=status.command_sequence,
                result=status.ack_result,
            )
        return status

    def _simulated_result(self) -> Stage3BStatus:
        return Stage3BStatus(
            state=self._state,
            selected_source_id=self._selected_source_id,
            sample_cycle_id=self._sample_cycle_id,
            command_sequence=self._command_sequence,
            ack_result=self._ack_result,
            rejection_reason=self._rejection_reason,
            admissible=False,
            safe_reset_required=self._safe_reset_required,
            fixed_request=SIMULATED_TEST_POWER,
        )

    def _reject_simulated(self, reason: str) -> Stage3BStatus:
        self._state = Stage3AState.REJECTED
        self._rejection_reason = reason
        self._diagnostic_log.append(
            "SIMULATED_TEST_REJECTED",
            reason=reason,
            emonio_device_id=self._selected_source_id,
            sequence=self._command_sequence,
            safe_reset_required=self._safe_reset_required,
        )
        return self._simulated_result()

    def _reject_simulated_and_raise(self, reason: str) -> None:
        self._reject_simulated(reason)
        raise Stage3AError(reason)

    @staticmethod
    def _simulated_ack_mismatch(command: CommandFrame, ack: AckFrame) -> str | None:
        if ack.protocol_version != LOAD_CONTROL_PROTOCOL_VERSION:
            return "ACK_PROTOCOL_MISMATCH"
        if ack.viewer_session_id != command.viewer_session_id:
            return "ACK_SESSION_MISMATCH"
        if ack.node_id != command.node_id:
            return "ACK_NODE_MISMATCH"
        if ack.boot_id != command.boot_id:
            return "ACK_BOOT_MISMATCH"
        if ack.sequence != command.sequence:
            return "ACK_SEQUENCE_MISMATCH"
        if ack.result != "APPLIED":
            return "ACK_RESULT_MISMATCH"
        if ack.applied_p != command.p_load_request:
            return "ACK_APPLIED_P_MISMATCH"
        return None

    def _log_simulated_status(self, frame: StatusFrame) -> None:
        self._diagnostic_log.append(
            "SIMULATED_STATUS_RECEIVED",
            node_id=frame.node_id,
            boot_id=frame.boot_id,
            state=frame.state,
            applied_p_a_w=frame.applied_p.a,
            applied_p_b_w=frame.applied_p.b,
            applied_p_c_w=frame.applied_p.c,
        )

    def _log_simulated_unexpected_ack(self, frame: AckFrame) -> None:
        self._diagnostic_log.append(
            "SIMULATED_ACK_UNEXPECTED",
            node_id=frame.node_id,
            boot_id=frame.boot_id,
            viewer_session_id=frame.viewer_session_id,
            sequence=frame.sequence,
            result=frame.result,
            applied_p_a_w=frame.applied_p.a,
            applied_p_b_w=frame.applied_p.b,
            applied_p_c_w=frame.applied_p.c,
        )

    async def _wait_for_simulated_ack(self, command: CommandFrame) -> Stage3BStatus:
        deadline_ns = self._monotonic_ns() + int(ACK_TIMEOUT_S * 1_000_000_000)
        self._state = Stage3AState.WAITING_FOR_ACK
        while True:
            remaining_s = (deadline_ns - self._monotonic_ns()) / 1_000_000_000.0
            if remaining_s <= 0.0:
                return self._reject_simulated("ACK_TIMEOUT")
            try:
                frame = await self._channel.receive(remaining_s)
            except asyncio.TimeoutError:
                return self._reject_simulated("ACK_TIMEOUT")
            except (ConnectionError, QualifiedActuatorChannelError):
                return self._reject_simulated("ACTUATOR_DISCONNECTED")
            except ProtocolError as exc:
                if "unsupported protocol_version" in _error_text(exc):
                    return self._reject_simulated("ACK_PROTOCOL_MISMATCH")
                return self._reject_simulated("UNEXPECTED_ACTUATOR_FRAME")
            except Exception:
                return self._reject_simulated("UNEXPECTED_ACTUATOR_FRAME")

            if isinstance(frame, StatusFrame):
                self._log_simulated_status(frame)
                continue
            if not isinstance(frame, AckFrame):
                return self._reject_simulated("UNEXPECTED_ACTUATOR_FRAME")

            if (
                frame.viewer_session_id == command.viewer_session_id
                and frame.sequence < command.sequence
            ):
                self._log_simulated_unexpected_ack(frame)
                continue

            self._diagnostic_log.append(
                "SIMULATED_ACK_RECEIVED",
                node_id=frame.node_id,
                boot_id=frame.boot_id,
                viewer_session_id=frame.viewer_session_id,
                sequence=frame.sequence,
                result=frame.result,
                applied_p_a_w=frame.applied_p.a,
                applied_p_b_w=frame.applied_p.b,
                applied_p_c_w=frame.applied_p.c,
            )
            mismatch = self._simulated_ack_mismatch(command, frame)
            if mismatch is not None:
                return self._reject_simulated(mismatch)

            self._ack_result = frame.result
            self._diagnostic_log.append(
                "SIMULATED_ACK_QUALIFIED",
                sequence=frame.sequence,
                result=frame.result,
                applied_p_a_w=frame.applied_p.a,
                applied_p_b_w=frame.applied_p.b,
                applied_p_c_w=frame.applied_p.c,
            )
            self._state = Stage3BState.RESET_REQUIRED
            self._rejection_reason = None
            self._diagnostic_log.append(
                "SIMULATED_TEST_APPLIED_RESET_REQUIRED",
                emonio_device_id=self._selected_source_id,
                sequence=frame.sequence,
                node_id=frame.node_id,
                boot_id=frame.boot_id,
                requested_p_a_w=command.p_load_request.a,
                requested_p_b_w=command.p_load_request.b,
                requested_p_c_w=command.p_load_request.c,
            )
            return self._simulated_result()

    async def run_simulated_test(self) -> Stage3BStatus:
        if self._active:
            raise Stage3AError("SAFE_TEST_ACTIVE")
        if self._safe_reset_required:
            raise Stage3AError("SAFE_RESET_REQUIRED")

        self._active = True
        try:
            if not self._started:
                self._reject_simulated_and_raise("SOURCE_NOT_AVAILABLE")
            source = self._source_config(self._selected_source_id)
            if source is None:
                self._reject_simulated_and_raise(
                    "SOURCE_NOT_SELECTED"
                    if self._selected_source_id is None
                    else "SOURCE_NOT_AVAILABLE"
                )
            assert source is not None
            if not _valid_poll_interval(source.poll_interval_s):
                self._reject_simulated_and_raise("SOURCE_NOT_AVAILABLE")

            hello = self._channel.hello()
            if hello is None:
                self._reject_simulated_and_raise("ACTUATOR_NOT_QUALIFIED")
            assert hello is not None

            self._drain_unsolicited_actuator_frames()
            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject_simulated("ACTUATOR_DISCONNECTED")

            self._sample_cycle_id = None
            self._command_sequence = None
            self._ack_result = None
            self._rejection_reason = None
            boundary_cycle = self._latest_cycle_by_source.get(source.id, 0)
            request_monotonic_ns = self._monotonic_ns()
            self._diagnostic_log.append(
                "SIMULATED_TEST_REQUESTED",
                emonio_device_id=source.id,
                node_id=hello.node_id,
                boot_id=hello.boot_id,
                boundary_cycle_id=boundary_cycle,
                fixed_p_a_w=SIMULATED_TEST_POWER.a,
                fixed_p_b_w=SIMULATED_TEST_POWER.b,
                fixed_p_c_w=SIMULATED_TEST_POWER.c,
            )
            self._state = Stage3AState.WAITING_FOR_SAMPLE
            self._diagnostic_log.append(
                "SIMULATED_SAMPLE_WAIT_STARTED",
                emonio_device_id=source.id,
                boundary_cycle_id=boundary_cycle,
                timeout_s=2.0 * float(source.poll_interval_s),
            )

            try:
                sample = await self._next_valid_sample(
                    source=source,
                    boundary_cycle=boundary_cycle,
                    request_monotonic_ns=request_monotonic_ns,
                )
            except _SourceAcquisitionFailure:
                return self._reject_simulated("SOURCE_ACQUISITION_FAILURE")
            except _ActuatorDisconnected:
                return self._reject_simulated("ACTUATOR_DISCONNECTED")
            if sample is None:
                return self._reject_simulated("NO_NEW_VALID_SAMPLE")

            self._sample_cycle_id = sample.identity.cycle_id
            measured_p = ThreePhasePower(
                sample.phase_a.measurement.p,
                sample.phase_b.measurement.p,
                sample.phase_c.measurement.p,
            )
            measured_q = ThreePhasePower(
                sample.phase_a.measurement.q,
                sample.phase_b.measurement.q,
                sample.phase_c.measurement.q,
            )
            self._diagnostic_log.append(
                "SIMULATED_SAMPLE_ACCEPTED",
                emonio_device_id=source.id,
                measurement_cycle_id=sample.identity.cycle_id,
                measurement_utc=_aware_iso(sample.timing.cycle_finished_utc, "measurement_utc"),
                measured_p_a_w=measured_p.a,
                measured_p_b_w=measured_p.b,
                measured_p_c_w=measured_p.c,
                measured_q_a_var=measured_q.a,
                measured_q_b_var=measured_q.b,
                measured_q_c_var=measured_q.c,
            )

            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject_simulated("ACTUATOR_DISCONNECTED")

            self._drain_unsolicited_actuator_frames()
            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject_simulated("ACTUATOR_DISCONNECTED")

            if current_hello.p_max.a < SIMULATED_TEST_POWER.a:
                return self._reject_simulated("SIMULATED_TEST_LIMIT_INSUFFICIENT")

            sequence = self._next_sequence
            self._next_sequence += 1
            self._command_sequence = sequence
            command = CommandFrame(
                protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
                viewer_session_id=self._viewer_session_id,
                node_id=hello.node_id,
                boot_id=hello.boot_id,
                sequence=sequence,
                emonio_device_id=source.id,
                measurement_cycle_id=sample.identity.cycle_id,
                measurement_utc=_aware_iso(sample.timing.cycle_finished_utc, "measurement_utc"),
                command_utc=_aware_iso(self._utc_now(), "command_utc"),
                control_enabled=True,
                p_reserve=SIMULATED_TEST_P_RESERVE_W,
                measured_p=measured_p,
                measured_q=measured_q,
                p_load_request=SIMULATED_TEST_POWER,
                q_comp_request=ZERO_POWER,
            )

            self._ack_wait_active = True
            self._safe_reset_required = True
            try:
                try:
                    await self._channel.send(command)
                except (ConnectionError, QualifiedActuatorChannelError):
                    return self._reject_simulated("ACTUATOR_DISCONNECTED")
                except Exception:
                    return self._reject_simulated("COMMAND_SEND_FAILED")

                self._state = Stage3AState.COMMAND_SENT
                self._diagnostic_log.append(
                    "SIMULATED_COMMAND_SENT",
                    emonio_device_id=source.id,
                    measurement_cycle_id=sample.identity.cycle_id,
                    viewer_session_id=command.viewer_session_id,
                    node_id=command.node_id,
                    boot_id=command.boot_id,
                    sequence=command.sequence,
                    control_enabled=command.control_enabled,
                    requested_p_a_w=command.p_load_request.a,
                    requested_p_b_w=command.p_load_request.b,
                    requested_p_c_w=command.p_load_request.c,
                )
                return await self._wait_for_simulated_ack(command)
            finally:
                self._ack_wait_active = False
        finally:
            self._active = False
