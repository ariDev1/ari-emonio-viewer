import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.server.keys import LAN_ACTUATOR_DISCOVERY_SERVICE_KEY
from emonio_viewer.server.load_control_api import register_load_control_routes


class FakeLanDiscoveryService:
    def __init__(self) -> None:
        self.calls = []

    async def scan(self, *, discovery_window_s: float, resolve_timeout_s: float):
        self.calls.append((discovery_window_s, resolve_timeout_s))
        return (
            ActuatorDescriptor(
                node_id="ARI-LOAD-001",
                location="ws://192.168.20.44:8765/control",
                device_class="ARI_LOAD_ACTUATOR",
                capabilities=("ACTIVE_LOAD_CONTROL",),
                p_max=ThreePhasePower(1200.0, 1200.0, 1200.0),
            ),
        )


async def _request(app, body):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post("/api/v1/load-control/lan-discovery/scan", json=body)
            payload = await response.json() if response.content_type == "application/json" else await response.text()
            return response.status, payload


def test_lan_discovery_api_requires_explicit_timing_and_returns_read_only_results() -> None:
    async def scenario() -> None:
        service = FakeLanDiscoveryService()
        app = web.Application()
        app[LAN_ACTUATOR_DISCOVERY_SERVICE_KEY] = service
        register_load_control_routes(app)

        status, payload = await _request(
            app,
            {"discovery_window_s": 0.25, "resolve_timeout_s": 0.15},
        )

        assert status == 200
        assert service.calls == [(0.25, 0.15)]
        assert payload == [
            {
                "node_id": "ARI-LOAD-001",
                "location": "ws://192.168.20.44:8765/control",
                "device_class": "ARI_LOAD_ACTUATOR",
                "capabilities": ["ACTIVE_LOAD_CONTROL"],
                "p_max": {"a": 1200.0, "b": 1200.0, "c": 1200.0},
            }
        ]

        status, payload = await _request(app, {"discovery_window_s": 0.25})
        assert status == 400
        assert "resolve_timeout_s" in payload

    asyncio.run(scenario())
