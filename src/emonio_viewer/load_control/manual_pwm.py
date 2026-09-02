from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import math

from .protocol import AckFrame, LOAD_CONTROL_PROTOCOL_VERSION, ProtocolError, StatusFrame
from .pwm_protocol import PwmAckFrame, PwmCommandFrame
from .qualified_channel import QualifiedActuatorChannelError
from .stage3a import ACK_TIMEOUT_S, Stage3AError, _error_text
from .stage3b import Stage3BExplicitCommandService


PWM_DUTY_CONTROL_CAPABILITY = "PWM_DUTY_CONTROL"


class ManualPwmState(str, Enum):
    IDLE = "IDLE"
    DISCONNECTED = "DISCONNECTED"
    UNSUPPORTED = "UNSUPPORTED"
    READY = "READY"
    COMMAND_SENT = "COMMAND_SENT"
    WAITING_FOR_ACK = "WAITING_FOR_ACK"
    APPLIED = "APPLIED"
    OFF = "OFF"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ManualPwmStatus:
    state: ManualPwmState
    node_id: str | None
    boot_id: str | None
    command_sequence: int | None
    ack_result: str | None
    rejection_reason: str | None
    requested_duty_percent: float | None
    actual_duty_percent: float | None
    compare_ticks: int | None
    period_ticks: int | None
    admissible: bool


class Stage3BManualPwmCommandService(Stage3BExplicitCommandService):
    """Add explicit manual PWM duty control to the qualified actuator channel.

    Manual PWM control is independent of Emonio measurement data. It does not
    select a measurement source, read a sample, calculate watts, or map watts
    to duty. It reuses the existing Viewer session and sequence owner so all
    actuator commands remain in one deterministic sequence namespace.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._manual_pwm_state = ManualPwmState.IDLE
        self._manual_pwm_boot_id: str | None = None
        self._manual_pwm_sequence: int | None = None
        self._manual_pwm_ack_result: str | None = None
        self._manual_pwm_rejection_reason: str | None = None
        self._manual_pwm_requested_duty: float | None = None
        self._manual_pwm_actual_duty: float | None = None
        self._manual_pwm_compare_ticks: int | None = None
        self._manual_pwm_period_ticks: int | None = None
        self._pwm_owner: str | None = None

    @property
    def pwm_owner(self) -> str | None:
        return self._pwm_owner

    def reserve_pwm_owner(self, owner: str) -> None:
        if not isinstance(owner, str) or not owner.strip():
            raise Stage3AError("PWM_OWNER_INVALID")
        if self._active:
            raise Stage3AError("CONTROL_COMMAND_ACTIVE")
        if self._pwm_owner is not None:
            raise Stage3AError("PWM_OWNER_RESERVED")
        self._pwm_owner = owner

    def release_pwm_owner(self, owner: str) -> None:
        if self._pwm_owner != owner:
            raise Stage3AError("PWM_OWNER_MISMATCH")
        if self._active:
            raise Stage3AError("CONTROL_COMMAND_ACTIVE")
        self._pwm_owner = None

    @staticmethod
    def _valid_manual_duty(value: float) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and 0.0 <= float(value) < 100.0
        )

    def _clear_manual_result(self) -> None:
        self._manual_pwm_boot_id = None
        self._manual_pwm_sequence = None
        self._manual_pwm_ack_result = None
        self._manual_pwm_rejection_reason = None
        self._manual_pwm_requested_duty = None
        self._manual_pwm_actual_duty = None
        self._manual_pwm_compare_ticks = None
        self._manual_pwm_period_ticks = None

    def manual_pwm_status(self) -> ManualPwmStatus:
        hello = self._channel.hello()
        if not self._started:
            state = ManualPwmState.IDLE
            admissible = False
            expose_result = False
        elif hello is None:
            state = ManualPwmState.DISCONNECTED
            admissible = False
            expose_result = False
        elif PWM_DUTY_CONTROL_CAPABILITY not in hello.capabilities:
            state = ManualPwmState.UNSUPPORTED
            admissible = False
            expose_result = False
        elif self._manual_pwm_boot_id is not None and self._manual_pwm_boot_id != hello.boot_id:
            state = ManualPwmState.READY
            admissible = not self._active and self._pwm_owner is None
            expose_result = False
        else:
            state = self._manual_pwm_state
            if state in {ManualPwmState.IDLE, ManualPwmState.DISCONNECTED, ManualPwmState.UNSUPPORTED}:
                state = ManualPwmState.READY
            admissible = not self._active and self._pwm_owner is None
            expose_result = True

        return ManualPwmStatus(
            state=state,
            node_id=(hello.node_id if hello is not None else None),
            boot_id=(hello.boot_id if hello is not None else None),
            command_sequence=(self._manual_pwm_sequence if expose_result else None),
            ack_result=(self._manual_pwm_ack_result if expose_result else None),
            rejection_reason=(self._manual_pwm_rejection_reason if expose_result else None),
            requested_duty_percent=(self._manual_pwm_requested_duty if expose_result else None),
            actual_duty_percent=(self._manual_pwm_actual_duty if expose_result else None),
            compare_ticks=(self._manual_pwm_compare_ticks if expose_result else None),
            period_ticks=(self._manual_pwm_period_ticks if expose_result else None),
            admissible=admissible,
        )

    def _manual_reject(self, reason: str) -> ManualPwmStatus:
        self._manual_pwm_state = ManualPwmState.REJECTED
        self._manual_pwm_rejection_reason = reason
        self._manual_pwm_ack_result = None
        self._diagnostic_log.append(
            "PWM_COMMAND_REJECTED",
            reason=reason,
            sequence=self._manual_pwm_sequence,
            requested_duty_percent=self._manual_pwm_requested_duty,
        )
        return self.manual_pwm_status()

    def _manual_reject_and_raise(self, reason: str) -> None:
        self._manual_reject(reason)
        raise Stage3AError(reason)

    @staticmethod
    def _pwm_ack_mismatch(command: PwmCommandFrame, ack: PwmAckFrame) -> str | None:
        if ack.protocol_version != LOAD_CONTROL_PROTOCOL_VERSION:
            return "PWM_ACK_PROTOCOL_MISMATCH"
        if ack.viewer_session_id != command.viewer_session_id:
            return "PWM_ACK_SESSION_MISMATCH"
        if ack.node_id != command.node_id:
            return "PWM_ACK_NODE_MISMATCH"
        if ack.boot_id != command.boot_id:
            return "PWM_ACK_BOOT_MISMATCH"
        if ack.sequence != command.sequence:
            return "PWM_ACK_SEQUENCE_MISMATCH"
        if ack.result != "APPLIED":
            return "PWM_ACK_RESULT_MISMATCH"
        if ack.requested_duty_percent != command.duty_percent:
            return "PWM_ACK_REQUESTED_DUTY_MISMATCH"
        if command.duty_percent == 0.0:
            if ack.actual_duty_percent != 0.0 or ack.compare_ticks != 0:
                return "PWM_ACK_OFF_MISMATCH"
        elif ack.actual_duty_percent <= 0.0 or ack.compare_ticks <= 0:
            return "PWM_ACK_APPLIED_DUTY_MISMATCH"
        return None

    def _log_pwm_status(self, frame: StatusFrame) -> None:
        self._diagnostic_log.append(
            "PWM_STATUS_RECEIVED",
            node_id=frame.node_id,
            boot_id=frame.boot_id,
            state=frame.state,
        )

    async def _wait_for_pwm_ack(self, command: PwmCommandFrame) -> ManualPwmStatus:
        deadline_ns = self._monotonic_ns() + int(ACK_TIMEOUT_S * 1_000_000_000)
        self._manual_pwm_state = ManualPwmState.WAITING_FOR_ACK
        while True:
            remaining_s = (deadline_ns - self._monotonic_ns()) / 1_000_000_000.0
            if remaining_s <= 0.0:
                return self._manual_reject("PWM_ACK_TIMEOUT")
            try:
                frame = await self._channel.receive(remaining_s)
            except asyncio.TimeoutError:
                return self._manual_reject("PWM_ACK_TIMEOUT")
            except (ConnectionError, QualifiedActuatorChannelError):
                return self._manual_reject("ACTUATOR_DISCONNECTED")
            except ProtocolError as exc:
                if "unsupported protocol_version" in _error_text(exc):
                    return self._manual_reject("PWM_ACK_PROTOCOL_MISMATCH")
                return self._manual_reject("PWM_UNEXPECTED_ACTUATOR_FRAME")
            except Exception:
                return self._manual_reject("PWM_UNEXPECTED_ACTUATOR_FRAME")

            if isinstance(frame, StatusFrame):
                self._log_pwm_status(frame)
                continue
            if isinstance(frame, AckFrame):
                return self._manual_reject("PWM_UNEXPECTED_POWER_ACK")
            if not isinstance(frame, PwmAckFrame):
                return self._manual_reject("PWM_UNEXPECTED_ACTUATOR_FRAME")

            if (
                frame.viewer_session_id == command.viewer_session_id
                and frame.sequence < command.sequence
            ):
                self._diagnostic_log.append(
                    "PWM_ACK_STALE",
                    sequence=frame.sequence,
                    expected_sequence=command.sequence,
                )
                continue

            mismatch = self._pwm_ack_mismatch(command, frame)
            if mismatch is not None:
                return self._manual_reject(mismatch)

            self._manual_pwm_ack_result = frame.result
            self._manual_pwm_rejection_reason = None
            self._manual_pwm_requested_duty = frame.requested_duty_percent
            self._manual_pwm_actual_duty = frame.actual_duty_percent
            self._manual_pwm_compare_ticks = frame.compare_ticks
            self._manual_pwm_period_ticks = frame.period_ticks
            self._manual_pwm_state = (
                ManualPwmState.OFF
                if frame.requested_duty_percent == 0.0
                else ManualPwmState.APPLIED
            )
            self._diagnostic_log.append(
                "PWM_ACK_QUALIFIED",
                node_id=frame.node_id,
                boot_id=frame.boot_id,
                sequence=frame.sequence,
                requested_duty_percent=frame.requested_duty_percent,
                actual_duty_percent=frame.actual_duty_percent,
                compare_ticks=frame.compare_ticks,
                period_ticks=frame.period_ticks,
            )
            return self.manual_pwm_status()

    async def _run_pwm(self, duty_percent: float, *, owner: str | None) -> ManualPwmStatus:
        if not self._valid_manual_duty(duty_percent):
            raise Stage3AError("PWM_DUTY_INVALID")
        if owner is None:
            if self._pwm_owner is not None:
                raise Stage3AError("PWM_OWNER_RESERVED")
        elif self._pwm_owner != owner:
            raise Stage3AError("PWM_OWNER_MISMATCH")
        if self._active:
            raise Stage3AError("CONTROL_COMMAND_ACTIVE")

        self._active = True
        try:
            if not self._started:
                self._manual_reject_and_raise("PWM_SERVICE_NOT_STARTED")

            hello = self._channel.hello()
            if hello is None:
                self._manual_reject_and_raise("ACTUATOR_NOT_QUALIFIED")
            assert hello is not None
            if PWM_DUTY_CONTROL_CAPABILITY not in hello.capabilities:
                self._manual_reject_and_raise("PWM_DUTY_CONTROL_NOT_SUPPORTED")

            self._drain_unsolicited_actuator_frames()
            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                self._manual_reject("ACTUATOR_DISCONNECTED")
            else:
                sequence = self._next_sequence
                self._next_sequence += 1
                self._clear_manual_result()
                self._manual_pwm_boot_id = hello.boot_id
                self._manual_pwm_sequence = sequence
                self._manual_pwm_requested_duty = float(duty_percent)

                command = PwmCommandFrame(
                    protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
                    viewer_session_id=self._viewer_session_id,
                    node_id=hello.node_id,
                    boot_id=hello.boot_id,
                    sequence=sequence,
                    duty_percent=float(duty_percent),
                )

                self._ack_wait_active = True
                try:
                    sent = False
                    try:
                        await self._channel.send_pwm(command)
                        sent = True
                    except (ConnectionError, QualifiedActuatorChannelError):
                        self._manual_reject("ACTUATOR_DISCONNECTED")
                    except Exception:
                        self._manual_reject("PWM_COMMAND_SEND_FAILED")

                    if sent:
                        self._manual_pwm_state = ManualPwmState.COMMAND_SENT
                        self._diagnostic_log.append(
                            "PWM_COMMAND_SENT",
                            node_id=command.node_id,
                            boot_id=command.boot_id,
                            viewer_session_id=command.viewer_session_id,
                            sequence=command.sequence,
                            requested_duty_percent=command.duty_percent,
                        )
                        await self._wait_for_pwm_ack(command)
                finally:
                    self._ack_wait_active = False
        finally:
            self._active = False

        return self.manual_pwm_status()

    async def run_manual_pwm(self, duty_percent: float) -> ManualPwmStatus:
        return await self._run_pwm(duty_percent, owner=None)

    async def run_reserved_pwm(self, duty_percent: float, *, owner: str) -> ManualPwmStatus:
        return await self._run_pwm(duty_percent, owner=owner)

    async def close(self) -> None:
        await super().close()
        self._manual_pwm_state = ManualPwmState.IDLE
        self._pwm_owner = None
        self._clear_manual_result()
