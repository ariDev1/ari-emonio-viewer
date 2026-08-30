from dataclasses import dataclass
from enum import Enum


class AcquisitionLifecycleState(str, Enum):
    RUNNING = "RUNNING"
    DISCONNECTING = "DISCONNECTING"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class AcquisitionStatus:
    device_id: str
    state: AcquisitionLifecycleState
    detail: str | None = None


class AcquisitionTransitionError(RuntimeError):
    def __init__(self, status: AcquisitionStatus) -> None:
        super().__init__(status.detail or status.state.value)
        self.status = status
