import asyncio
from pathlib import Path

import pytest

from emonio_viewer.config.loader import ConfigError
from emonio_viewer.main import SERVER_HOST, load_runtime_config, shutdown_runtime


def run_lifecycle_with_invalid_config(tmp_path: Path) -> list[str]:
    path = tmp_path / "invalid.toml"
    path.write_text(
        """
[viewer]
default_device = "meter"
[recording]
default_interval_s = 10
[[devices]]
id = "meter"
name = "meter"
host = "192.0.2.1"
poll_interval_s = 0
""",
        encoding="utf-8",
    )
    trace: list[str] = []
    with pytest.raises(ConfigError):
        load_runtime_config(path, trace=trace)
    return trace


class FakeRecording:
    def disable_commands(self) -> None:
        pass

    def stop_all(self) -> None:
        pass


class FakeCoordinator:
    def stop(self) -> None:
        pass

    def close_clients(self) -> None:
        pass


async def _stop_server() -> None:
    return None


def run_lifecycle_shutdown_trace() -> list[str]:
    trace: list[str] = []
    asyncio.run(
        shutdown_runtime(
            FakeRecording(),
            FakeCoordinator(),
            _stop_server,
            trace=trace,
        )
    )
    return trace


def test_startup_validates_config_before_starting_workers(tmp_path: Path) -> None:
    trace = run_lifecycle_with_invalid_config(tmp_path)
    assert trace == ["LOAD_CONFIG", "VALIDATE_CONFIG", "FAIL"]


def test_shutdown_stops_recorders_before_workers_and_server() -> None:
    trace = run_lifecycle_shutdown_trace()
    assert trace == [
        "STOP_RECORDING_COMMANDS",
        "STOP_RECORDERS",
        "STOP_WORKERS",
        "STOP_SERVER",
    ]


def test_server_default_is_localhost_only() -> None:
    assert SERVER_HOST == "127.0.0.1"


def test_coordinator_explicit_close_closes_client(fake_emonio, device_config) -> None:
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    coordinator = AcquisitionCoordinator((device_config,), RuntimeStore(), RuntimeEventBus())
    worker = coordinator._workers[device_config.id]
    worker.client.connect()
    assert worker.client.is_connected is True
    coordinator.close_clients()
    assert worker.client.is_connected is False


def test_recording_manager_disable_commands_blocks_new_recording(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.recording.recorder import RecordingManager
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    manager = RecordingManager(tmp_path, (device_config,), store, RuntimeEventBus(), "0.1.0")
    manager.disable_commands()
    with pytest.raises(RuntimeError, match="disabled"):
        manager.start(device_config.id, 5.0)
    manager.stop_all()


def test_runtime_config_loads_remembered_devices_beside_toml(tmp_path: Path) -> None:
    from emonio_viewer.config.device_registry import RememberedDeviceRegistry
    from emonio_viewer.config.model import DeviceConfig

    path = tmp_path / "emonio-viewer.toml"
    path.write_text(
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
    RememberedDeviceRegistry(tmp_path / "remembered-devices.json").remember(
        DeviceConfig(id="remembered", name="remembered", host="192.0.2.12")
    )

    config = load_runtime_config(path)

    assert [device.id for device in config.devices] == ["fixed", "remembered"]


class HangingModbusServer:
    """Accept one Modbus request and hold the TCP response open until stopped."""

    def __init__(self) -> None:
        import socket
        import threading

        self.request_received = threading.Event()
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self.host, self.port = self._listener.getsockname()
        self._listener.listen(1)
        self._connection = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        import socket

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


def test_coordinator_stop_interrupts_blocked_modbus_receive() -> None:
    import time

    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.config.model import DeviceConfig
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    server = HangingModbusServer()
    server.start()
    device = DeviceConfig(
        id="blocking-meter",
        name="blocking-meter",
        host=server.host,
        port=server.port,
        poll_interval_s=2.0,
        timeout_s=5.0,
    )
    coordinator = AcquisitionCoordinator((device,), RuntimeStore(), RuntimeEventBus())
    coordinator.start()
    try:
        assert server.request_received.wait(1.0)
        started = time.monotonic()
        coordinator.stop(join_timeout_s=0.75)
        elapsed = time.monotonic() - started
    finally:
        server.stop()
        coordinator.close_clients()

    assert elapsed < 0.75


def test_shutdown_runtime_continues_workers_and_server_after_recording_failure() -> None:
    calls = []

    class FailingRecording:
        def disable_commands(self):
            calls.append("disable")

        def stop_all(self):
            calls.append("recorders")
            raise RuntimeError("recording finalization failed")

    class TrackingCoordinator:
        def stop(self):
            calls.append("workers")

    async def stop_server():
        calls.append("server")

    async def exercise():
        with pytest.raises(RuntimeError) as exc_info:
            await shutdown_runtime(FailingRecording(), TrackingCoordinator(), stop_server)
        return str(exc_info.value)

    message = asyncio.run(exercise())
    assert calls == ["disable", "recorders", "workers", "server"]
    assert "recording finalization failed" in message


def test_scope_cleanup_failure_does_not_block_canonical_shutdown() -> None:
    import emonio_viewer.main as main_module

    calls = []

    class FailingScope:
        async def close(self):
            calls.append("scope")
            raise RuntimeError("scope close failed")

    class TrackingRecording:
        def disable_commands(self):
            calls.append("disable")

        def stop_all(self):
            calls.append("recorders")

    class TrackingCoordinator:
        def stop(self):
            calls.append("workers")

    async def stop_server():
        calls.append("server")

    async def exercise():
        with pytest.raises(RuntimeError) as exc_info:
            await main_module.shutdown_viewer(
                FailingScope(),
                TrackingRecording(),
                TrackingCoordinator(),
                stop_server,
                coordinator_started=True,
            )
        return str(exc_info.value)

    message = asyncio.run(exercise())
    assert calls == ["scope", "disable", "recorders", "workers", "server"]
    assert "scope close failed" in message
