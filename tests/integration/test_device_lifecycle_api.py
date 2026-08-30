from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import WSMsgType
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


class FakeLifecycleService:
    def __init__(self) -> None:
        self.state = "RUNNING"
        self.calls: list[tuple[str, str]] = []
        self.failure: DeviceLifecycleResult | None = None

    def status(self, device_id: str) -> DeviceLifecycleResult:
        return DeviceLifecycleResult(
            device_id=device_id,
            acquisition_state=self.state,
            measurement_state="ONLINE",
            recording_state="STOPPED",
            scope_state="DISCONNECTED",
        )

    async def disconnect(self, device_id: str) -> DeviceLifecycleResult:
        self.calls.append(("disconnect", device_id))
        if self.failure is not None:
            raise DeviceLifecycleCommandError(self.failure)
        self.state = "DISCONNECTED"
        return self.status(device_id)

    async def reconnect(self, device_id: str) -> DeviceLifecycleResult:
        self.calls.append(("reconnect", device_id))
        if self.failure is not None:
            raise DeviceLifecycleCommandError(self.failure)
        self.state = "RUNNING"
        return self.status(device_id)


def build_app(tmp_path: Path, real_sample, device_config, lifecycle: FakeLifecycleService):
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(
        ViewerConfig(device_config.id),
        RecordingConfig(10.0),
        (device_config,),
    )
    app = create_app(
        config,
        store,
        bus,
        NoopRecordingManager(),
        frontend,
        lifecycle_service=lifecycle,
    )
    return app, bus


async def get_json(app, path: str):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.get(path)
            return response.status, await response.json()


async def post_json(app, path: str):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(path, json={})
            return response.status, await response.json()


def test_lifecycle_disconnect_and_reconnect_routes_are_backend_authoritative(
    tmp_path,
    real_sample,
    device_config,
) -> None:
    lifecycle = FakeLifecycleService()
    app, _ = build_app(tmp_path, real_sample, device_config, lifecycle)

    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/disconnect")
    )
    assert status == 200
    assert payload["device_id"] == device_config.id
    assert payload["acquisition_state"] == "DISCONNECTED"
    assert payload["recording_state"] == "STOPPED"
    assert payload["scope_state"] == "DISCONNECTED"
    assert payload["failed_stage"] is None

    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/reconnect")
    )
    assert status == 200
    assert payload["acquisition_state"] == "RUNNING"
    assert lifecycle.calls == [
        ("disconnect", device_config.id),
        ("reconnect", device_config.id),
    ]


def test_lifecycle_failure_returns_structured_partial_completion(
    tmp_path,
    real_sample,
    device_config,
) -> None:
    lifecycle = FakeLifecycleService()
    lifecycle.failure = DeviceLifecycleResult(
        device_id=device_config.id,
        acquisition_state="RUNNING",
        measurement_state="ONLINE",
        recording_state="STOPPED",
        scope_state="DISCONNECTED",
        failed_stage=LifecycleFailureStage.ACQUISITION,
        detail="worker did not stop",
    )
    app, _ = build_app(tmp_path, real_sample, device_config, lifecycle)

    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/disconnect")
    )

    assert status == 502
    assert payload["failed_stage"] == "ACQUISITION"
    assert payload["recording_state"] == "STOPPED"
    assert payload["scope_state"] == "DISCONNECTED"
    assert payload["acquisition_state"] == "RUNNING"
    assert payload["detail"] == "worker did not stop"


def test_lifecycle_routes_reject_unknown_device_before_service_call(
    tmp_path,
    real_sample,
    device_config,
) -> None:
    lifecycle = FakeLifecycleService()
    app, _ = build_app(tmp_path, real_sample, device_config, lifecycle)

    status, _ = asyncio.run(post_json(app, "/api/v1/devices/missing/disconnect"))

    assert status == 404
    assert lifecycle.calls == []


def test_read_routes_add_acquisition_state_without_renaming_measurement_state(
    tmp_path,
    real_sample,
    device_config,
) -> None:
    lifecycle = FakeLifecycleService()
    app, _ = build_app(tmp_path, real_sample, device_config, lifecycle)

    status, devices = asyncio.run(get_json(app, "/api/v1/devices"))
    assert status == 200
    assert devices[0]["acquisition_state"] == "RUNNING"
    assert devices[0]["state"] == "ONLINE"

    status, device = asyncio.run(get_json(app, f"/api/v1/devices/{device_config.id}"))
    assert status == 200
    assert device["acquisition_state"] == "RUNNING"
    assert device["state"] == "ONLINE"
    assert device["sample"]["phase_b"]["p"] == real_sample.phase_b.measurement.p

    status, diagnostics = asyncio.run(
        get_json(app, f"/api/v1/diagnostics/{device_config.id}")
    )
    assert status == 200
    assert diagnostics["acquisition_state"] == "RUNNING"
    assert diagnostics["state"] == "ONLINE"


def test_websocket_adds_acquisition_state_without_changing_canonical_sample(
    tmp_path,
    real_sample,
    device_config,
) -> None:
    lifecycle = FakeLifecycleService()
    app, bus = build_app(tmp_path, real_sample, device_config, lifecycle)

    async def exercise():
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                ws = await client.ws_connect("/ws/v1/measurements")
                bus.publish(real_sample)
                message = await ws.receive(timeout=1.0)
                assert message.type is WSMsgType.TEXT
                payload = message.json()
                await ws.close()
                return payload

    payload = asyncio.run(exercise())
    assert payload["acquisition_state"] == "RUNNING"
    assert payload["state"] == "ONLINE"
    assert payload["sample"]["phase_a"]["p"] == real_sample.phase_a.measurement.p
    assert payload["sample"]["phase_b"]["q"] == real_sample.phase_b.measurement.q
    assert payload["sample"]["phase_c"]["pf"] == real_sample.phase_c.measurement.pf
