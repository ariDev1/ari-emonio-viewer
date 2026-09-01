from __future__ import annotations

from enum import Enum

from .model import ControlMode, SafeState


class TripReason(str, Enum):
    MEASUREMENT_NOT_VALID = "MEASUREMENT_NOT_VALID"
    CONTROL_SAMPLE_STALE = "CONTROL_SAMPLE_STALE"
    CONTROL_SAMPLE_SEQUENCE_GAP = "CONTROL_SAMPLE_SEQUENCE_GAP"
    ACQUISITION_FAILURE = "ACQUISITION_FAILURE"
    ACTUATOR_CONNECTION_LOST = "ACTUATOR_CONNECTION_LOST"
    ACTUATOR_IDENTITY_MISMATCH = "ACTUATOR_IDENTITY_MISMATCH"
    ACTUATOR_BOOT_CHANGED = "ACTUATOR_BOOT_CHANGED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CAPABILITY_CHANGED = "CAPABILITY_CHANGED"
    ACK_INVALID = "ACK_INVALID"
    ACK_TIMEOUT = "ACK_TIMEOUT"
    EVIDENCE_WRITE_FAILED = "EVIDENCE_WRITE_FAILED"


class ControlStateMachine:
    def __init__(self) -> None:
        self.mode = ControlMode.DISABLED
        self.safe_state = SafeState.SAFE_UNCONFIRMED
        self.trip_reason: TripReason | None = None

    def enable(self) -> None:
        self.mode = ControlMode.ENABLED
        self.safe_state = SafeState.NOT_REQUIRED
        self.trip_reason = None

    def disable(self) -> None:
        if self.mode is not ControlMode.TRIPPED:
            self.mode = ControlMode.DISABLED
            self.trip_reason = None
        self.safe_state = SafeState.SAFE_UNCONFIRMED

    def trip(self, reason: TripReason) -> None:
        if not isinstance(reason, TripReason):
            raise ValueError("reason must be TripReason")
        self.mode = ControlMode.TRIPPED
        self.safe_state = SafeState.SAFE_UNCONFIRMED
        self.trip_reason = reason

    def mark_safe_unconfirmed(self) -> None:
        self.safe_state = SafeState.SAFE_UNCONFIRMED

    def mark_safe_confirmed(self) -> None:
        self.safe_state = SafeState.SAFE_CONFIRMED
