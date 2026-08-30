from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.lifecycle.model import (
    DeviceLifecycleCommandError,
    DeviceLifecycleResult,
    LifecycleFailureStage,
)
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app


class NoopRecordingManager:
    def active_recordings(self):
        return ()

    def recording_failures(self):
        return ()


class FailingLifecycleService:
    def __init__(self, result: DeviceLifecycleResult, *, conflict: bool) -> None:
        self.result = result
        self.conflict = conflict

    def status(self, _device_id):
        return self.result

    async def disconnect(self, _device_id):
        raise DeviceLifecycleCommandError(self.result, conflict=self.conflict)

    async def reconnect(self, _device_id):
        raise DeviceLifecycleCommandError(self.result, conflict=self.conflict)


def _app(tmp_path: Path, real_sample, device_config, lifecycle) -> object:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    config = RuntimeConfig(
        ViewerConfig(device_config.id),
        RecordingConfig(10.0),
        (device_config,),
    )
    return create_app(
        config,
        store,
        RuntimeEventBus(),
        NoopRecordingManager(),
        frontend,
        lifecycle_service=lifecycle,
    )


async def _post(app, path: str):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(path, json={})
            return response.status, await response.json()


def test_proven_disconnect_transition_conflict_returns_409(tmp_path, real_sample, device_config) -> None:
    result = DeviceLifecycleResult(
        device_id=device_config.id,
        acquisition_state="DISCONNECTED",
        measurement_state="ONLINE",
        recording_state="STOPPED",
        scope_state="DISCONNECTED",
        failed_stage=LifecycleFailureStage.ACQUISITION,
        detail="acquisition is not RUNNING",
    )
    app = _app(tmp_path, real_sample, device_config, FailingLifecycleService(result, conflict=True))

    status, payload = asyncio.run(
        _post(app, f"/api/v1/devices/{device_config.id}/disconnect")
    )

    assert status == 409
    assert payload["failed_stage"] == "ACQUISITION"
    assert payload["acquisition_state"] == "DISCONNECTED"


def test_cleanup_failure_remains_502(tmp_path, real_sample, device_config) -> None:
    result = DeviceLifecycleResult(
        device_id=device_config.id,
        acquisition_state="ERROR",
        measurement_state="ONLINE",
        recording_state="STOPPED",
        scope_state="DISCONNECTED",
        failed_stage=LifecycleFailureStage.ACQUISITION,
        detail="acquisition worker did not stop within 5 s",
    )
    app = _app(tmp_path, real_sample, device_config, FailingLifecycleService(result, conflict=False))

    status, payload = asyncio.run(
        _post(app, f"/api/v1/devices/{device_config.id}/disconnect")
    )

    assert status == 502
    assert payload["acquisition_state"] == "ERROR"
