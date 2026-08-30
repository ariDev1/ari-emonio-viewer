from __future__ import annotations

import asyncio
import json
from queue import Empty
from types import SimpleNamespace
import time

from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.lifecycle.service import DeviceLifecycleService
from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from tests.fixtures.real_device_samples import PHASE_A_WORDS, PHASE_B_WORDS, PHASE_C_WORDS, TOTAL_WORDS
from tests.integration.fake_emonio import FakeEmonioServer


def _loaded_server() -> FakeEmonioServer:
    server = FakeEmonioServer()
    for base, words in (
        (0, PHASE_A_WORDS),
        (100, PHASE_B_WORDS),
        (200, PHASE_C_WORDS),
        (300, TOTAL_WORDS),
    ):
        server.set_block(base, words)
    server.start()
    return server


def _wait_until(predicate, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_lifecycle_service_releases_one_device_end_to_end(tmp_path, monkeypatch) -> None:
    servers = tuple(_loaded_server() for _ in range(3))
    devices = tuple(
        DeviceConfig(
            id=f"handoff-{index}",
            name=f"handoff-{index}",
            host=server.host,
            port=server.port,
            poll_interval_s=0.2,
            timeout_s=0.1,
            firmware_version="3.0.79-release",
        )
        for index, server in enumerate(servers, start=1)
    )
    middle = devices[1]
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator(devices, store, bus)
    recording = RecordingManager(tmp_path / "recordings", devices, store, bus, "0.4.14-test")
    trace: list[str] = []

    class OrderedScope:
        def __init__(self) -> None:
            self.states = {middle.id: "LIVE"}

        def status(self, device_id):
            return SimpleNamespace(
                device_id=device_id,
                state=SimpleNamespace(value=self.states.get(device_id, "DISCONNECTED")),
            )

        async def stop(self, device_id):
            trace.append("scope")
            self.states[device_id] = "DISCONNECTED"
            return self.status(device_id)

    scope = OrderedScope()
    original_recording_stop = recording.stop
    original_disconnect = coordinator.disconnect_device

    def traced_recording_stop(device_id):
        trace.append("recording")
        return original_recording_stop(device_id)

    def traced_disconnect(device_id, join_timeout_s=5.0):
        trace.append("acquisition")
        return original_disconnect(device_id, join_timeout_s=join_timeout_s)

    monkeypatch.setattr(recording, "stop", traced_recording_stop)
    monkeypatch.setattr(coordinator, "disconnect_device", traced_disconnect)
    service = DeviceLifecycleService(coordinator, recording, scope, store)
    subscriber = None

    coordinator.start()
    recording.start_background()
    try:
        _wait_until(lambda: all(store.get_device(device.id).cycles_valid >= 2 for device in devices))
        session_dir = recording.start(middle.id, middle.poll_interval_s)
        assert any(item["device_id"] == middle.id for item in recording.active_recordings())

        async def exercise() -> None:
            nonlocal subscriber

            disconnected = await service.disconnect(middle.id)
            assert disconnected.acquisition_state == "DISCONNECTED"
            assert disconnected.recording_state == "STOPPED"
            assert disconnected.scope_state == "DISCONNECTED"
            assert trace[:3] == ["recording", "scope", "acquisition"]

            metadata = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            assert "stopped_utc" in metadata
            assert coordinator._threads[middle.id].is_alive() is False
            assert coordinator._workers[middle.id].client.is_connected is False

            stopped_snapshot = store.get_device(middle.id)
            assert stopped_snapshot.last_sample is not None
            stopped_cycle = stopped_snapshot.last_sample.identity.cycle_id
            first_before = store.get_device(devices[0].id).cycles_valid
            third_before = store.get_device(devices[2].id).cycles_valid
            _wait_until(lambda: store.get_device(devices[0].id).cycles_valid > first_before)
            _wait_until(lambda: store.get_device(devices[2].id).cycles_valid > third_before)
            time.sleep(0.25)
            current_middle = store.get_device(middle.id).last_sample
            assert current_middle is not None
            assert current_middle.identity.cycle_id == stopped_cycle

            subscriber = bus.subscribe(maxsize=64)
            reconnected = await service.reconnect(middle.id)
            assert reconnected.acquisition_state == "RUNNING"
            assert not any(item["device_id"] == middle.id for item in recording.active_recordings())
            assert scope.status(middle.id).state.value == "DISCONNECTED"

            middle_cycles: list[int] = []
            deadline = time.monotonic() + 2.0
            while len(middle_cycles) < 2 and time.monotonic() < deadline:
                try:
                    event = subscriber.get(timeout=0.2)
                except Empty:
                    continue
                if isinstance(event, MeasurementSample) and event.identity.device_id == middle.id:
                    middle_cycles.append(event.identity.cycle_id)
            assert middle_cycles[:2] == [stopped_cycle + 1, stopped_cycle + 2]
            assert coordinator._threads[middle.id].is_alive() is True
            assert coordinator._workers[middle.id].client.is_connected is True

        asyncio.run(exercise())
    finally:
        if subscriber is not None:
            bus.unsubscribe(subscriber)
        try:
            recording.stop_all()
        finally:
            try:
                coordinator.stop()
            except RuntimeError:
                pass
            coordinator.close_clients()
            for server in servers:
                server.stop()
