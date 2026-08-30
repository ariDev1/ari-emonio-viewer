from dataclasses import dataclass
from enum import Enum


class LifecycleFailureStage(str, Enum):
    RECORDING = "RECORDING"
    SCOPE = "SCOPE"
    ACQUISITION = "ACQUISITION"


@dataclass(frozen=True, slots=True)
class DeviceLifecycleResult:
    device_id: str
    acquisition_state: str
    measurement_state: str
    recording_state: str
    scope_state: str
    failed_stage: LifecycleFailureStage | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "acquisition_state": self.acquisition_state,
            "measurement_state": self.measurement_state,
            "recording_state": self.recording_state,
            "scope_state": self.scope_state,
            "failed_stage": None if self.failed_stage is None else self.failed_stage.value,
            "detail": self.detail,
        }


class DeviceLifecycleCommandError(RuntimeError):
    def __init__(self, result: DeviceLifecycleResult) -> None:
        super().__init__(result.detail or "device lifecycle command failed")
        self.result = result
