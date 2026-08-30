from __future__ import annotations

import socket
import threading
import time

import pytest

from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
from emonio_viewer.acquisition.lifecycle import (
    AcquisitionLifecycleState,
    AcquisitionStatus,
    AcquisitionTransitionError,
)
from emonio_viewer.config.model import DeviceConfig
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


@pytest.fixture
def three_device_coordinator():
    servers = tuple(_loaded_server() for _ in range(3))
    devices = tuple(
        DeviceConfig(
            id=f"emonio-{index}",
            name=f"emonio-{index}",
            host=server.host,
            port=server.port,
            poll_interval_s=0.05,
            timeout_s=0.1,
            firmware_version="3.0.79-release",
        )
        for index, server in enumerate(servers, start=1)
    )
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator(devices, store, RuntimeEventBus())
    try:
        yield coordinator, store, devices
    finally:
        try:
            coordinator.stop()
        except RuntimeError:
            pass
        coordinator.close_clients()
        for server in servers:
            server.stop()


def wait_until(predicate, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_disconnect_one_device_keeps_other_workers_running(three_device_coordinator) -> None:
    coordinator, store, devices = three_device_coordinator
    coordinator.start()
    wait_until(lambda: all(store.get_device(device.id).cycles_valid >= 2 for device in devices))
    before = {device.id: store.get_device(device.id).cycles_valid for device in devices}

    status = coordinator.disconnect_device(devices[1].id)

    assert status.state is AcquisitionLifecycleState.DISCONNECTED
    assert coordinator.get_device_config(devices[1].id) == devices[1]
    assert coordinator._threads[devices[1].id].is_alive() is False
    assert coordinator._workers[devices[1].id].client.is_connected is False
    assert coordinator.acquisition_status(devices[0].id).state is AcquisitionLifecycleState.RUNNING
    assert coordinator.acquisition_status(devices[2].id).state is AcquisitionLifecycleState.RUNNING
    wait_until(lambda: store.get_device(devices[0].id).cycles_valid > before[devices[0].id])
    wait_until(lambda: store.get_device(devices[2].id).cycles_valid > before[devices[2].id])
    time.sleep(0.12)
    assert store.get_device(devices[1].id).cycles_valid == before[devices[1].id]


def test_global_stop_tolerates_one_device_already_disconnected(three_device_coordinator) -> None:
    coordinator, store, devices = three_device_coordinator
    coordinator.start()
    wait_until(lambda: all(store.get_device(device.id).cycles_valid >= 1 for device in devices))
    coordinator.disconnect_device(devices[1].id)

    coordinator.stop()

    assert all(not thread.is_alive() for thread in coordinator._threads.values())


class HangingModbusServer:
    def __init__(self) -> None:
        self.request_received = threading.Event()
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self.host, self.port = self._listener.getsockname()
        self._listener.listen(1)
        self._connection: socket.socket | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        try:
            socket.create_connection((self.host, self.port), timeout=0.05).close()
        except OSError:
            pass
        self._listener.close()
        self._thread.join(timeout=1.0)

    def _serve(self) -> None:
        try:
            connection, _ = self._listener.accept()
        except OSError:
            return
        self._connection = connection
        with connection:
            try:
                request = connection.recv(64)
            except OSError:
                return
            if request:
                self.request_received.set()
            self._stop.wait(10.0)


def test_disconnect_interrupts_only_selected_blocked_receive(fake_emonio) -> None:
    hanging = HangingModbusServer()
    hanging.start()
    healthy = DeviceConfig(
        id="healthy",
        name="healthy",
        host=fake_emonio.host,
        port=fake_emonio.port,
        poll_interval_s=0.05,
        timeout_s=0.1,
    )
    blocked = DeviceConfig(
        id="blocked",
        name="blocked",
        host=hanging.host,
        port=hanging.port,
        poll_interval_s=2.0,
        timeout_s=5.0,
    )
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((healthy, blocked), store, RuntimeEventBus())
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(healthy.id).cycles_valid >= 1)
        assert hanging.request_received.wait(1.0)
        healthy_before = store.get_device(healthy.id).cycles_valid

        started = time.monotonic()
        status = coordinator.disconnect_device(blocked.id, join_timeout_s=0.75)
        elapsed = time.monotonic() - started

        assert status.state is AcquisitionLifecycleState.DISCONNECTED
        assert elapsed < 0.75
        wait_until(lambda: store.get_device(healthy.id).cycles_valid > healthy_before)
        assert coordinator.acquisition_status(healthy.id).state is AcquisitionLifecycleState.RUNNING
    finally:
        coordinator.stop()
        coordinator.close_clients()
        hanging.stop()


def test_reconnect_uses_next_cycle_id_fresh_worker_and_one_reconnect_metric(
    fake_emonio,
    device_config,
) -> None:
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((device_config,), store, RuntimeEventBus())
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device_config.id).cycles_valid >= 2)
        before = store.get_device(device_config.id)
        assert before.last_sample is not None
        old_worker = coordinator._workers[device_config.id]
        before_cycle = before.last_sample.identity.cycle_id
        before_reconnects = before.metrics.reconnects

        coordinator.disconnect_device(device_config.id)
        status = coordinator.reconnect_device(device_config.id)

        assert status.state is AcquisitionLifecycleState.RUNNING
        assert coordinator._workers[device_config.id] is not old_worker
        qualified = store.get_device(device_config.id)
        assert qualified.last_sample is not None
        assert qualified.last_sample.identity.cycle_id == before_cycle + 1
        assert qualified.metrics.reconnects == before_reconnects + 1
        wait_until(
            lambda: (
                store.get_device(device_config.id).last_sample is not None
                and store.get_device(device_config.id).last_sample.identity.cycle_id
                >= before_cycle + 2
            )
        )
    finally:
        coordinator.stop()
        coordinator.close_clients()


def test_failed_reconnect_keeps_last_exact_sample_and_closes_candidate(
    fake_emonio,
    device_config,
    monkeypatch,
) -> None:
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((device_config,), store, RuntimeEventBus())
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device_config.id).cycles_valid >= 1)
        coordinator.disconnect_device(device_config.id)
        before = store.get_device(device_config.id)
        assert before.last_sample is not None
        old_worker = coordinator._workers[device_config.id]
        old_thread = coordinator._threads[device_config.id]
        captured_workers = []
        original_create_worker = coordinator._create_worker

        def capture_worker(*args, **kwargs):
            worker = original_create_worker(*args, **kwargs)
            captured_workers.append(worker)
            return worker

        monkeypatch.setattr(coordinator, "_create_worker", capture_worker)
        fake_emonio.fail_all_reads("exception")

        with pytest.raises(AcquisitionTransitionError):
            coordinator.reconnect_device(device_config.id)

        after = store.get_device(device_config.id)
        assert coordinator.acquisition_status(device_config.id).state is AcquisitionLifecycleState.DISCONNECTED
        assert coordinator._workers[device_config.id] is old_worker
        assert coordinator._threads[device_config.id] is old_thread
        assert old_thread.is_alive() is False
        assert len(captured_workers) == 1
        assert captured_workers[0].client.is_connected is False
        assert after.last_sample is before.last_sample
        assert after.cycles_valid == before.cycles_valid
        assert after.cycles_invalid == before.cycles_invalid
    finally:
        coordinator.stop()
        coordinator.close_clients()


def test_reconnect_rejects_running_connecting_live_previous_thread_and_global_stop(
    fake_emonio,
    device_config,
) -> None:
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((device_config,), store, RuntimeEventBus())
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device_config.id).cycles_valid >= 1)
        original_worker = coordinator._workers[device_config.id]

        with pytest.raises(AcquisitionTransitionError):
            coordinator.reconnect_device(device_config.id)
        assert coordinator._workers[device_config.id] is original_worker

        coordinator._lifecycle[device_config.id] = AcquisitionStatus(
            device_config.id,
            AcquisitionLifecycleState.CONNECTING,
        )
        with pytest.raises(AcquisitionTransitionError):
            coordinator.reconnect_device(device_config.id)
        assert coordinator._workers[device_config.id] is original_worker

        coordinator._lifecycle[device_config.id] = AcquisitionStatus(
            device_config.id,
            AcquisitionLifecycleState.DISCONNECTED,
        )
        assert coordinator._threads[device_config.id].is_alive() is True
        with pytest.raises(AcquisitionTransitionError):
            coordinator.reconnect_device(device_config.id)
        assert coordinator._workers[device_config.id] is original_worker
    finally:
        coordinator.stop()
        coordinator.close_clients()

    assert coordinator.acquisition_status(device_config.id).state is AcquisitionLifecycleState.DISCONNECTED
    with pytest.raises(AcquisitionTransitionError):
        coordinator.reconnect_device(device_config.id)
    assert coordinator._workers[device_config.id] is original_worker
