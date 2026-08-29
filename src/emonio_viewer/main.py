from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
import signal
import sys

from aiohttp import web

from emonio_viewer import __version__
from emonio_viewer.acquisition.connector import DeviceConnector
from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
from emonio_viewer.acquisition.state import DeviceState
from emonio_viewer.config.device_registry import RememberedDeviceRegistry
from emonio_viewer.config.loader import load_config, merge_runtime_devices
from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.device_evidence.modbus import ModbusDeviceEvidenceReader
from emonio_viewer.device_evidence.service import CtConfigurationService, ModbusDeviceEvidenceService
from emonio_viewer.device_evidence.telnet import TelnetCtConfigurationReader
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app
from emonio_viewer.scope.service import ScopeService


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8787
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _trace(trace: list[str] | None, item: str) -> None:
    if trace is not None:
        trace.append(item)


def load_runtime_config(path: Path, trace: list[str] | None = None) -> RuntimeConfig:
    """Load and validate the complete runtime configuration before startup."""
    _trace(trace, "LOAD_CONFIG")
    _trace(trace, "VALIDATE_CONFIG")
    try:
        config = load_config(path)
        registry = RememberedDeviceRegistry(path.parent / "remembered-devices.json")
        return merge_runtime_devices(config, registry.load())
    except Exception:
        _trace(trace, "FAIL")
        raise


async def wait_for_initial_device_evidence(
    store: RuntimeStore,
    config: RuntimeConfig,
) -> None:
    enabled = tuple(device for device in config.devices if device.enabled)
    if not enabled:
        return

    timeout_s = max(device.timeout_s for device in enabled) + 2.0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    expected_ids = {device.id for device in enabled}

    while True:
        snapshots = {snapshot.device_id: snapshot for snapshot in store.list_devices()}
        ready = True
        for device_id in expected_ids:
            snapshot = snapshots.get(device_id)
            if snapshot is None:
                ready = False
                break
            if snapshot.last_sample is None and snapshot.state is not DeviceState.OFFLINE:
                ready = False
                break
        if ready:
            return
        if loop.time() >= deadline:
            return
        await asyncio.sleep(0.05)


async def shutdown_runtime(
    recording: RecordingManager,
    coordinator: AcquisitionCoordinator,
    stop_server: Callable[[], Awaitable[None]],
    *,
    trace: list[str] | None = None,
    stop_workers: bool = True,
) -> None:
    cleanup_errors: list[str] = []

    _trace(trace, "STOP_RECORDING_COMMANDS")
    try:
        recording.disable_commands()
    except Exception as exc:
        cleanup_errors.append(f"STOP_RECORDING_COMMANDS: {str(exc) or type(exc).__name__}")

    _trace(trace, "STOP_RECORDERS")
    try:
        recording.stop_all()
    except Exception as exc:
        cleanup_errors.append(f"STOP_RECORDERS: {str(exc) or type(exc).__name__}")

    if stop_workers:
        _trace(trace, "STOP_WORKERS")
        try:
            coordinator.stop()
        except Exception as exc:
            cleanup_errors.append(f"STOP_WORKERS: {str(exc) or type(exc).__name__}")

    _trace(trace, "STOP_SERVER")
    try:
        await stop_server()
    except Exception as exc:
        cleanup_errors.append(f"STOP_SERVER: {str(exc) or type(exc).__name__}")

    if cleanup_errors:
        raise RuntimeError("runtime cleanup failed: " + "; ".join(cleanup_errors))


async def shutdown_viewer(
    scope_service: ScopeService,
    recording: RecordingManager,
    coordinator: AcquisitionCoordinator,
    stop_server: Callable[[], Awaitable[None]],
    *,
    coordinator_started: bool,
    trace: list[str] | None = None,
) -> None:
    cleanup_errors: list[str] = []
    try:
        await scope_service.close()
    except Exception as exc:
        cleanup_errors.append(f"SCOPE: {str(exc) or type(exc).__name__}")

    try:
        await shutdown_runtime(
            recording,
            coordinator,
            stop_server,
            trace=trace,
            stop_workers=coordinator_started,
        )
    except Exception as exc:
        cleanup_errors.append(str(exc) or type(exc).__name__)

    if cleanup_errors:
        raise RuntimeError("viewer cleanup failed: " + "; ".join(cleanup_errors))


async def run_viewer(config_path: Path) -> None:
    config = load_runtime_config(config_path)
    store = RuntimeStore()
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator(config.devices, store, bus)
    recordings_root = PROJECT_ROOT / "recordings"
    recording = RecordingManager(recordings_root, config.devices, store, bus, __version__)
    registry = RememberedDeviceRegistry(config_path.parent / "remembered-devices.json")
    connector = DeviceConnector(coordinator, recording, registry=registry)
    ct_configuration = CtConfigurationService(TelnetCtConfigurationReader())
    modbus_evidence = ModbusDeviceEvidenceService(
        ModbusDeviceEvidenceReader(),
        coordinator=coordinator,
    )
    scope_service = ScopeService()
    recording.start_background()

    frontend_dir = PROJECT_ROOT / "frontend"
    if not frontend_dir.is_dir():
        raise FileNotFoundError(f"frontend directory not found: {frontend_dir}")

    runner: web.AppRunner | None = None
    coordinator_started = False
    shutdown_event = asyncio.Event()

    try:
        coordinator.start()
        coordinator_started = True
        await wait_for_initial_device_evidence(store, config)

        app = create_app(
            config,
            store,
            bus,
            recording,
            frontend_dir,
            connector=connector,
            ct_configuration=ct_configuration,
            modbus_evidence=modbus_evidence,
            scope_service=scope_service,
        )
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, SERVER_HOST, SERVER_PORT)
        await site.start()

        print(f"ARI Emonio Viewer v{__version__}")
        print(f"Viewer: http://{SERVER_HOST}:{SERVER_PORT}")
        print(f"Config: {config_path}")
        print("Press Ctrl+C to stop.")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown_event.set)
            except NotImplementedError:
                pass

        await shutdown_event.wait()
    finally:
        async def stop_server() -> None:
            if runner is not None:
                await runner.cleanup()

        await shutdown_viewer(
            scope_service,
            recording,
            coordinator,
            stop_server,
            coordinator_started=coordinator_started,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARI Emonio Viewer")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "emonio-viewer.toml",
        help="Path to viewer TOML configuration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        asyncio.run(run_viewer(args.config))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ARI Emonio Viewer: ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
