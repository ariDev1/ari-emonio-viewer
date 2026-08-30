from dataclasses import replace
import json
from pathlib import Path

import pytest

from emonio_viewer.config.device_registry import (
    DeviceRegistryError,
    RememberedDeviceRegistry,
)
from emonio_viewer.config.model import DeviceConfig


def _device(*, device_id: str = "emonio-b", host: str = "192.0.2.12") -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        name=device_id,
        host=host,
        port=502,
        unit_id=1,
        poll_interval_s=2.0,
        timeout_s=2.0,
        enabled=True,
        firmware_version="unknown",
    )


def test_missing_registry_loads_empty(tmp_path: Path) -> None:
    registry = RememberedDeviceRegistry(tmp_path / "remembered-devices.json")
    assert registry.load() == ()


def test_registry_round_trip_is_atomic_and_preserves_device_fields(tmp_path: Path) -> None:
    path = tmp_path / "remembered-devices.json"
    registry = RememberedDeviceRegistry(path)
    device = _device()

    registry.remember(device)

    assert registry.load() == (device,)
    assert not (tmp_path / "remembered-devices.json.tmp").exists()


def test_registry_persists_only_fixed_device_configuration_fields(tmp_path: Path) -> None:
    path = tmp_path / "remembered-devices.json"
    registry = RememberedDeviceRegistry(path)
    registry.remember(_device())

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert set(raw) == {"schema_version", "devices"}
    assert raw["schema_version"] == 1
    assert len(raw["devices"]) == 1
    assert set(raw["devices"][0]) == {
        "id",
        "name",
        "host",
        "port",
        "unit_id",
        "poll_interval_s",
        "timeout_s",
        "enabled",
        "firmware_version",
    }
    serialized = json.dumps(raw).lower()
    for forbidden in ("password", "ct_invert", "ct_type", "measurement", "session_note"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("poll_interval_s", float("nan")),
        ("poll_interval_s", float("inf")),
        ("timeout_s", float("nan")),
        ("timeout_s", float("inf")),
    ),
)
def test_registry_rejects_non_finite_timing_values(
    tmp_path: Path, field: str, value: float
) -> None:
    registry = RememberedDeviceRegistry(tmp_path / "remembered-devices.json")
    device = replace(_device(), **{field: value})

    with pytest.raises(DeviceRegistryError, match=field):
        registry.remember(device)

    assert not registry.path.exists()


def test_registry_rejects_duplicate_device_ids(tmp_path: Path) -> None:
    path = tmp_path / "remembered-devices.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "devices": [
                    {
                        "id": "same", "name": "one", "host": "192.0.2.12", "port": 502,
                        "unit_id": 1, "poll_interval_s": 2.0, "timeout_s": 2.0,
                        "enabled": True, "firmware_version": "unknown"
                    },
                    {
                        "id": "same", "name": "two", "host": "192.0.2.13", "port": 502,
                        "unit_id": 1, "poll_interval_s": 2.0, "timeout_s": 2.0,
                        "enabled": True, "firmware_version": "unknown"
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeviceRegistryError, match="duplicate device id"):
        RememberedDeviceRegistry(path).load()


def test_registry_rejects_duplicate_device_hosts(tmp_path: Path) -> None:
    path = tmp_path / "remembered-devices.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "devices": [
                    {
                        "id": "one", "name": "one", "host": "192.0.2.12", "port": 502,
                        "unit_id": 1, "poll_interval_s": 2.0, "timeout_s": 2.0,
                        "enabled": True, "firmware_version": "unknown"
                    },
                    {
                        "id": "two", "name": "two", "host": "192.0.2.12", "port": 502,
                        "unit_id": 1, "poll_interval_s": 2.0, "timeout_s": 2.0,
                        "enabled": True, "firmware_version": "unknown"
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeviceRegistryError, match="duplicate device host"):
        RememberedDeviceRegistry(path).load()


def test_registry_rejects_malformed_or_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "remembered-devices.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DeviceRegistryError, match="invalid JSON"):
        RememberedDeviceRegistry(path).load()

    path.write_text(json.dumps({"schema_version": 2, "devices": []}), encoding="utf-8")
    with pytest.raises(DeviceRegistryError, match="schema_version"):
        RememberedDeviceRegistry(path).load()
