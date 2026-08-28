from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    id: str
    name: str
    host: str
    port: int = 502
    unit_id: int = 1
    poll_interval_s: float = 2.0
    timeout_s: float = 2.0
    enabled: bool = True
    firmware_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class ViewerConfig:
    default_device: str


@dataclass(frozen=True, slots=True)
class RecordingConfig:
    default_interval_s: float


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    viewer: ViewerConfig
    recording: RecordingConfig
    devices: tuple[DeviceConfig, ...]
