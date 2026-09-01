import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.qualification import (
    LoadControlQualificationError,
    QualificationState,
    QualificationStatus,
)
from emonio_viewer.server.keys import (
    LAN_ACTUATOR_DISCOVERY_SERVICE_KEY,
    LOAD_CONTROL_QUALIFICATION_SERVICE_KEY,
    LOAD_CONTROL_SERVICE_KEY,
)
from emonio_viewer.server.load_control_api import register_load_control_routes


class ForbiddenStage1Service:
    async def configure_binding(self, *args, **kwargs):
        raise AssertionError("Stage-2 route called configure_binding")

    async def enable(self):
        raise AssertionError("Stage-2 route called enable")

    async def disable(self):
        raise AssertionError("Stage-2 route called disable")


class FakeLanDiscoveryService:
    def __init__(self) -> None:
        self.calls = []

    async def scan(self, *, discovery_window_s: float, resolve_timeout_s: float):
        self.calls.append((discovery_window_s, resolve_timeout_s))
        return (
            ActuatorDescriptor(
                node_id="ARI-LOAD-001",
                location="ws://192.168.1.141:8080/load-control",
                device_class="ARI_LOAD_ACTUATOR",
                capabilities=("ACTIVE_LOAD_CONTROL",),
                p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
            ),
        )


class FakeQualificationService:
    def __init__(self) -> None:
        self.connect_calls = []
        self.disconnect_calls = 0
        self.reject_connect = False
        self.current = QualificationStatus(
            state=QualificationState.IDLE,
            connected=False,
            hello_qualified=False,
            selected_node_id=None,
            node_id=None,
            boot_id=None,
            protocol_version=None,
            device_class=None,
            capabilities=(),
            p_max=None,
            location=None,
            last_error=None,
        )

    def status(self) -> QualificationStatus:
        return self.current

    async def connect(self, node_id: str) -> QualificationStatus:
        if self.reject_connect:
            raise LoadControlQualificationError("a Stage-2 actuator connection is already open")
        self.connect_calls.append(node_id)
        self.current = QualificationStatus(
            state=QualificationState.QUALIFIED,
            connected=True,
            hello_qualified=True,
            selected_node_id=node_id,
            node_id=node_id,
            boot_id="BOOT-001",
            protocol_version=1,
            device_class="ARI_LOAD_ACTUATOR",
            capabilities=("ACTIVE_LOAD_CONTROL",),
            p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
            location="ws://192.168.1.141:8080/load-control",
            last_error=None,
        )
        return self.current

    async def disconnect(self) -> QualificationStatus:
        self.disconnect_calls += 1
        self.current = QualificationStatus(
            state=QualificationState.DISCONNECTED,
            connected=False,
            hello_qualified=False,
            selected_node_id="ARI-LOAD-001",
            node_id=None,
            boot_id=None,
            protocol_version=None,
            device_class=None,
            capabilities=(),
            p_max=None,
            location="ws://192.168.1.141:8080/load-control",
            last_error=None,
        )
        return self.current


def _app(qualification=None, lan=None):
    app = web.Application()
    app[LOAD_CONTROL_SERVICE_KEY] = ForbiddenStage1Service()
    if qualification is not None:
        app[LOAD_CONTROL_QUALIFICATION_SERVICE_KEY] = qualification
    if lan is not None:
        app[LAN_ACTUATOR_DISCOVERY_SERVICE_KEY] = lan
    register_load_control_routes(app)
    return app


async def _request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = (
                await response.json()
                if response.content_type == "application/json"
                else await response.text()
            )
            return response.status, payload


def test_stage2_status_connect_and_disconnect_routes_are_separate_from_stage1() -> None:
    async def scenario() -> None:
        qualification = FakeQualificationService()
        app = _app(qualification=qualification)

        status, payload = await _request(
            app,
            "GET",
            "/api/v1/load-control/lan-qualification/status",
        )
        assert status == 200
        assert payload["state"] == "IDLE"
        assert payload["connected"] is False
        assert payload["hello_qualified"] is False

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-qualification/connect",
            {"node_id": "ARI-LOAD-001"},
        )
        assert status == 200
        assert qualification.connect_calls == ["ARI-LOAD-001"]
        assert payload == {
            "state": "QUALIFIED",
            "connected": True,
            "hello_qualified": True,
            "selected_node_id": "ARI-LOAD-001",
            "node_id": "ARI-LOAD-001",
            "boot_id": "BOOT-001",
            "protocol_version": 1,
            "device_class": "ARI_LOAD_ACTUATOR",
            "capabilities": ["ACTIVE_LOAD_CONTROL"],
            "p_max": {"a": 1000.0, "b": 1000.0, "c": 1000.0},
            "location": "ws://192.168.1.141:8080/load-control",
            "last_error": None,
        }

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-qualification/disconnect",
            {},
        )
        assert status == 200
        assert qualification.disconnect_calls == 1
        assert payload["state"] == "DISCONNECTED"
        assert payload["node_id"] is None
        assert payload["boot_id"] is None

    asyncio.run(scenario())


def test_stage2_connect_requires_node_id_and_maps_service_conflict_to_409() -> None:
    async def scenario() -> None:
        qualification = FakeQualificationService()
        app = _app(qualification=qualification)

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-qualification/connect",
            {},
        )
        assert status == 400
        assert "node_id is required" in payload

        qualification.reject_connect = True
        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-qualification/connect",
            {"node_id": "ARI-LOAD-001"},
        )
        assert status == 409
        assert "already open" in payload

    asyncio.run(scenario())


def test_existing_lan_scan_route_remains_read_only_with_stage2_routes_registered() -> None:
    async def scenario() -> None:
        qualification = FakeQualificationService()
        lan = FakeLanDiscoveryService()
        app = _app(qualification=qualification, lan=lan)

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-discovery/scan",
            {"discovery_window_s": 0.25, "resolve_timeout_s": 0.15},
        )

        assert status == 200
        assert lan.calls == [(0.25, 0.15)]
        assert qualification.connect_calls == []
        assert payload[0]["node_id"] == "ARI-LOAD-001"
        assert payload[0]["p_max"] == {"a": 1000.0, "b": 1000.0, "c": 1000.0}

    asyncio.run(scenario())
