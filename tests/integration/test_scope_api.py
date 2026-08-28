from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app
from emonio_viewer.scope.model import ScopeSessionState, ScopeStatus
from emonio_viewer.scope.service import ScopeServiceError, ScopeSessionConflict


class FakeRecordingManager:
    def active_recordings(self):
        return ()


class FakeScopeService:
    def __init__(self) -> None:
        self.calls = []
        self.states = {}

    def status(self, device_id):
        return self.states.get(
            device_id,
            ScopeStatus(device_id, ScopeSessionState.DISCONNECTED, None, None),
        )

    async def start(self, device_id, host, username, password):
        self.calls.append(("start", device_id, host, username, password))
        state = ScopeStatus(device_id, ScopeSessionState.LIVE, None, None)
        self.states[device_id] = state
        return state

    def hold(self, device_id):
        self.calls.append(("hold", device_id))
        state = ScopeStatus(device_id, ScopeSessionState.HOLD, None, None)
        self.states[device_id] = state
        return state

    def live(self, device_id):
        self.calls.append(("live", device_id))
        state = ScopeStatus(device_id, ScopeSessionState.LIVE, None, None)
        self.states[device_id] = state
        return state

    async def stop(self, device_id):
        self.calls.append(("stop", device_id))
        state = ScopeStatus(device_id, ScopeSessionState.DISCONNECTED, None, None)
        self.states[device_id] = state
        return state


async def _request(app, method: str, path: str, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = await response.json() if response.content_type == "application/json" else await response.text()
            return response.status, payload


def _app(tmp_path, real_sample, device_config, scope_service):
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    return create_app(
        config,
        store,
        RuntimeEventBus(),
        FakeRecordingManager(),
        frontend,
        scope_service=scope_service,
    )


def test_scope_start_requires_operator_username_and_password_and_never_returns_them(tmp_path, real_sample, device_config) -> None:
    async def exercise():
        service = FakeScopeService()
        app = _app(tmp_path, real_sample, device_config, service)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                first = await client.post(
                    f"/api/v1/devices/{device_config.id}/scope/start", json={"password": "p"}
                )
                second = await client.post(
                    f"/api/v1/devices/{device_config.id}/scope/start", json={"username": "u"}
                )
                third = await client.post(
                    f"/api/v1/devices/{device_config.id}/scope/start",
                    json={"username": "admin", "password": "secret"},
                )
                return first.status, second.status, third.status, await third.json(), service.calls

    missing_user, missing_password, status, payload, calls = asyncio.run(exercise())
    assert missing_user == 400
    assert missing_password == 400
    assert status == 200
    assert calls == [("start", device_config.id, device_config.host, "admin", "secret")]
    encoded = str(payload)
    assert "admin" not in encoded
    assert "secret" not in encoded
    assert payload["state"] == "LIVE"
    assert payload["source"] == "EMONIO_WEBSOCKET_SCOPE"

def test_scope_status_and_control_routes_are_per_device(tmp_path, real_sample, device_config) -> None:
    async def exercise():
        service = FakeScopeService()
        app = _app(tmp_path, real_sample, device_config, service)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                initial = await client.get(f"/api/v1/devices/{device_config.id}/scope")
                initial_payload = await initial.json()
                await client.post(
                    f"/api/v1/devices/{device_config.id}/scope/start",
                    json={"username": "u", "password": "p"},
                )
                hold = await client.post(f"/api/v1/devices/{device_config.id}/scope/hold", json={})
                hold_payload = await hold.json()
                live = await client.post(f"/api/v1/devices/{device_config.id}/scope/live", json={})
                live_payload = await live.json()
                stop = await client.post(f"/api/v1/devices/{device_config.id}/scope/stop", json={})
                stop_payload = await stop.json()
                return (
                    initial.status, initial_payload,
                    hold.status, hold_payload,
                    live.status, live_payload,
                    stop.status, stop_payload,
                    service.calls,
                )

    (
        initial_status, initial_payload,
        hold_status, hold_payload,
        live_status, live_payload,
        stop_status, stop_payload,
        calls,
    ) = asyncio.run(exercise())
    assert initial_status == 200
    assert initial_payload["state"] == "DISCONNECTED"
    assert (hold_status, hold_payload["state"]) == (200, "HOLD")
    assert (live_status, live_payload["state"]) == (200, "LIVE")
    assert (stop_status, stop_payload["state"]) == (200, "DISCONNECTED")
    assert [call[0] for call in calls] == ["start", "hold", "live", "stop"]

def test_scope_routes_reject_unknown_device_before_scope_service_call(tmp_path, real_sample, device_config) -> None:
    service = FakeScopeService()
    app = _app(tmp_path, real_sample, device_config, service)
    status, _ = asyncio.run(
        _request(
            app,
            "POST",
            "/api/v1/devices/missing/scope/start",
            {"username": "u", "password": "p"},
        )
    )
    assert status == 404
    assert service.calls == []


def test_scope_service_errors_map_without_exposing_credentials(tmp_path, real_sample, device_config) -> None:
    class FailedScope(FakeScopeService):
        async def start(self, device_id, host, username, password):
            raise ScopeServiceError("scope login rejected")

    app = _app(tmp_path, real_sample, device_config, FailedScope())
    status, payload = asyncio.run(
        _request(
            app,
            "POST",
            f"/api/v1/devices/{device_config.id}/scope/start",
            {"username": "admin", "password": "secret"},
        )
    )
    assert status == 502
    assert "admin" not in str(payload)
    assert "secret" not in str(payload)


def test_scope_status_includes_compact_active_session_ownership_without_capture_duplication(tmp_path, real_sample, device_config) -> None:
    class MultiScope(FakeScopeService):
        def active_statuses(self):
            return (
                ScopeStatus("emonio-a", ScopeSessionState.LIVE, None, None),
                ScopeStatus("emonio-b", ScopeSessionState.HOLD, None, None),
            )

    async def exercise():
        service = MultiScope()
        app = _app(tmp_path, real_sample, device_config, service)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                response = await client.get(f"/api/v1/devices/{device_config.id}/scope")
                return response.status, await response.json()

    status, payload = asyncio.run(exercise())
    assert status == 200
    assert payload["active_sessions"] == [
        {"device_id": "emonio-a", "state": "LIVE"},
        {"device_id": "emonio-b", "state": "HOLD"},
    ]
    assert all("capture" not in item for item in payload["active_sessions"])
