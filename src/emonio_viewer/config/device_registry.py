from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model import DeviceConfig


SCHEMA_VERSION = 1
_DEVICE_FIELDS = (
    "id",
    "name",
    "host",
    "port",
    "unit_id",
    "poll_interval_s",
    "timeout_s",
    "enabled",
    "firmware_version",
)
_DEVICE_FIELD_SET = frozenset(_DEVICE_FIELDS)


class DeviceRegistryError(ValueError):
    """Raised when remembered-device evidence is structurally invalid."""


def _device_to_json(device: DeviceConfig) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.name,
        "host": device.host,
        "port": device.port,
        "unit_id": device.unit_id,
        "poll_interval_s": device.poll_interval_s,
        "timeout_s": device.timeout_s,
        "enabled": device.enabled,
        "firmware_version": device.firmware_version,
    }


def _device_from_json(raw: Any) -> DeviceConfig:
    if not isinstance(raw, dict):
        raise DeviceRegistryError("device entry must be an object")
    if set(raw) != _DEVICE_FIELD_SET:
        raise DeviceRegistryError("device entry fields do not match schema")

    try:
        device = DeviceConfig(**raw)
    except (TypeError, ValueError) as exc:
        raise DeviceRegistryError("device entry is invalid") from exc

    if not isinstance(device.id, str) or not device.id:
        raise DeviceRegistryError("device id must be non-empty text")
    if not isinstance(device.name, str) or not device.name:
        raise DeviceRegistryError("device name must be non-empty text")
    if not isinstance(device.host, str) or not device.host:
        raise DeviceRegistryError("device host must be non-empty text")
    if isinstance(device.port, bool) or not isinstance(device.port, int) or not 1 <= device.port <= 65535:
        raise DeviceRegistryError("device port must be 1..65535")
    if (
        isinstance(device.unit_id, bool)
        or not isinstance(device.unit_id, int)
        or not 0 <= device.unit_id <= 255
    ):
        raise DeviceRegistryError("device unit_id must be 0..255")
    if isinstance(device.poll_interval_s, bool) or not isinstance(device.poll_interval_s, (int, float)):
        raise DeviceRegistryError("device poll_interval_s must be numeric")
    if device.poll_interval_s <= 0:
        raise DeviceRegistryError("device poll_interval_s must be > 0")
    if isinstance(device.timeout_s, bool) or not isinstance(device.timeout_s, (int, float)):
        raise DeviceRegistryError("device timeout_s must be numeric")
    if device.timeout_s <= 0:
        raise DeviceRegistryError("device timeout_s must be > 0")
    if not isinstance(device.enabled, bool):
        raise DeviceRegistryError("device enabled must be boolean")
    if not isinstance(device.firmware_version, str):
        raise DeviceRegistryError("device firmware_version must be text")
    return device


class RememberedDeviceRegistry:
    """Atomic persistence for operator-qualified runtime device configuration."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[DeviceConfig, ...]:
        if not self.path.exists():
            return ()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DeviceRegistryError("invalid JSON in remembered device registry") from exc

        if not isinstance(raw, dict):
            raise DeviceRegistryError("remembered device registry must be an object")
        if set(raw) != {"schema_version", "devices"}:
            raise DeviceRegistryError("remembered device registry fields do not match schema")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise DeviceRegistryError("unsupported remembered device schema_version")
        if not isinstance(raw["devices"], list):
            raise DeviceRegistryError("remembered devices must be a list")

        devices = tuple(_device_from_json(item) for item in raw["devices"])
        ids: set[str] = set()
        hosts: set[str] = set()
        for device in devices:
            if device.id in ids:
                raise DeviceRegistryError("duplicate device id")
            if device.host in hosts:
                raise DeviceRegistryError("duplicate device host")
            ids.add(device.id)
            hosts.add(device.host)
        return devices

    def remember(self, device: DeviceConfig) -> None:
        # Round-trip through the registry schema before changing persistent state.
        qualified = _device_from_json(_device_to_json(device))
        devices = list(self.load())

        for existing in devices:
            if existing.id == qualified.id or existing.host == qualified.host:
                if existing == qualified:
                    return
                raise DeviceRegistryError("remembered device conflicts with existing id or host")

        devices.append(qualified)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "devices": [_device_to_json(item) for item in devices],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
