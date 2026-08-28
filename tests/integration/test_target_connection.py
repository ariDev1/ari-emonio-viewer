import asyncio

import pytest

from emonio_viewer.acquisition.connector import DeviceConnector, TargetConnectionError
from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore


class FakeRecordingRegistry:
    def __init__(self) -> None:
        self.devices = {}

    def register_device(self, device) -> None:
        self.devices[device.id] = device


def test_successful_target_probe_registers_only_after_complete_measurement(fake_emonio) -> None:
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    connector = DeviceConnector(
        coordinator,
        recording,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.1,
    )
    coordinator.start()
    try:
        result = asyncio.run(connector.connect(fake_emonio.host))
        snapshot = store.get_device(result.device.id)
    finally:
        coordinator.stop()
        coordinator.close_clients()

    assert result.device.host == fake_emonio.host
    assert snapshot.last_sample is not None
    assert snapshot.last_sample.phase_b.measurement.p < 0
    assert recording.devices[result.device.id] == result.device


def test_failed_target_probe_does_not_register_device(fake_emonio) -> None:
    fake_emonio.fail_all_reads("timeout")
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    connector = DeviceConnector(
        coordinator,
        recording,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.05,
    )
    coordinator.start()
    try:
        with pytest.raises(TargetConnectionError):
            asyncio.run(connector.connect(fake_emonio.host))
    finally:
        coordinator.stop()
        coordinator.close_clients()

    assert store.list_devices() == ()
    assert recording.devices == {}


def test_http_connect_route_uses_real_connector_and_publishes_sample(tmp_path, fake_emonio) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
    from emonio_viewer.server.app import create_app

    async def exercise(app):
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                response = await client.post("/api/v1/devices/connect", json={"target": fake_emonio.host})
                return response.status, await response.json()

    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    connector = DeviceConnector(
        coordinator,
        recording,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.1,
    )
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    config = RuntimeConfig(ViewerConfig("none"), RecordingConfig(10.0), ())
    app = create_app(config, store, bus, recording, frontend, connector=connector)

    coordinator.start()
    try:
        status, payload = asyncio.run(exercise(app))
        snapshot = store.get_device(payload["device_id"])
    finally:
        coordinator.stop()
        coordinator.close_clients()

    assert status == 200
    assert payload["state"] == "CONNECTED"
    assert snapshot.last_sample is not None
    assert snapshot.last_sample.phase_c.measurement.q < 0

class AssertingDeviceRegistry:
    def __init__(self, coordinator, recording) -> None:
        self._coordinator = coordinator
        self._recording = recording
        self.remembered = []

    def remember(self, device) -> None:
        assert self._coordinator.get_device_config(device.id) == device
        assert self._recording.devices[device.id] == device
        self.remembered.append(device)


def test_successful_target_is_remembered_after_live_registration(fake_emonio) -> None:
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    registry = AssertingDeviceRegistry(coordinator, recording)
    connector = DeviceConnector(
        coordinator,
        recording,
        registry=registry,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.1,
    )
    coordinator.start()
    try:
        result = asyncio.run(connector.connect(fake_emonio.host))
    finally:
        coordinator.stop()

    assert registry.remembered == [result.device]


def test_failed_target_is_not_remembered(fake_emonio) -> None:
    fake_emonio.fail_all_reads("timeout")
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    registry = AssertingDeviceRegistry(coordinator, recording)
    connector = DeviceConnector(
        coordinator,
        recording,
        registry=registry,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.05,
    )
    coordinator.start()
    try:
        with pytest.raises(TargetConnectionError):
            asyncio.run(connector.connect(fake_emonio.host))
    finally:
        coordinator.stop()

    assert registry.remembered == []


def test_qualified_target_reappears_after_fresh_runtime_config_load(tmp_path, fake_emonio) -> None:
    from emonio_viewer.config.device_registry import RememberedDeviceRegistry
    from emonio_viewer.main import load_runtime_config

    config_path = tmp_path / "emonio-viewer.toml"
    config_path.write_text(
        """
[viewer]
default_device = "fixed"
[recording]
default_interval_s = 10
[[devices]]
id = "fixed"
name = "fixed"
host = "192.0.2.11"
""",
        encoding="utf-8",
    )
    registry = RememberedDeviceRegistry(tmp_path / "remembered-devices.json")
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator((), store, bus)
    recording = FakeRecordingRegistry()
    connector = DeviceConnector(
        coordinator,
        recording,
        registry=registry,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.1,
    )
    coordinator.start()
    try:
        result = asyncio.run(connector.connect(fake_emonio.host))
    finally:
        coordinator.stop()

    fresh_config = load_runtime_config(config_path)

    assert [device.id for device in fresh_config.devices] == ["fixed", result.device.id]
    remembered = fresh_config.devices[1]
    assert remembered.host == fake_emonio.host
    assert remembered.port == fake_emonio.port
