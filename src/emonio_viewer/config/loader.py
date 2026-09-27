import math
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from .model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig


class ConfigError(ValueError):
    """Raised when viewer configuration is structurally invalid."""


def load_config(path: Path) -> RuntimeConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    devices = tuple(DeviceConfig(**item) for item in raw.get("devices", []))
    ids = [device.id for device in devices]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate device id")
    if not devices:
        raise ConfigError("at least one device is required")
    hosts = [device.host for device in devices]
    if len(hosts) != len(set(hosts)):
        raise ConfigError("duplicate device host")
    for device in devices:
        if not device.id or not isinstance(device.id, str):
            raise ConfigError("device id must be non-empty text")
        if not device.name or not isinstance(device.name, str):
            raise ConfigError("device name must be non-empty text")
        if not device.host or not isinstance(device.host, str):
            raise ConfigError("device host must be non-empty text")
        if not isinstance(device.enabled, bool):
            raise ConfigError("device enabled must be boolean")
        if not isinstance(device.firmware_version, str):
            raise ConfigError("device firmware_version must be text")
        if not math.isfinite(device.poll_interval_s) or device.poll_interval_s <= 0:
            raise ConfigError("poll_interval_s must be finite and > 0")
        if not math.isfinite(device.timeout_s) or device.timeout_s <= 0:
            raise ConfigError("timeout_s must be finite and > 0")
        if device.timeout_s > device.poll_interval_s:
            raise ConfigError("timeout_s must not exceed poll_interval_s")
        if not 1 <= device.port <= 65535:
            raise ConfigError("port must be 1..65535")
        if not 0 <= device.unit_id <= 255:
            raise ConfigError("unit_id must be 0..255")

    try:
        viewer = ViewerConfig(**raw["viewer"])
    except KeyError as exc:
        raise ConfigError(f"missing config section: {exc}") from exc
    try:
        recording = RecordingConfig(**raw["recording"])
    except KeyError as exc:
        raise ConfigError(f"missing config section: {exc}") from exc
    if viewer.default_device not in set(ids):
        raise ConfigError("default_device is not configured")
    if not math.isfinite(recording.default_interval_s) or recording.default_interval_s <= 0:
        raise ConfigError("recording default_interval_s must be finite and > 0")
    return RuntimeConfig(viewer=viewer, recording=recording, devices=devices)


def merge_runtime_devices(
    config: RuntimeConfig,
    remembered: tuple[DeviceConfig, ...],
) -> RuntimeConfig:
    """Merge remembered runtime devices while keeping TOML devices authoritative."""
    devices = list(config.devices)
    fixed_ids = {device.id for device in config.devices}
    fixed_hosts = {device.host for device in config.devices}
    for device in remembered:
        if device.id in fixed_ids or device.host in fixed_hosts:
            continue
        devices.append(device)
    return RuntimeConfig(
        viewer=config.viewer,
        recording=config.recording,
        devices=tuple(devices),
    )
