from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.service import LoadControlCommandError
from emonio_viewer.server.keys import LOAD_CONTROL_SERVICE_KEY
from emonio_viewer.server.load_control_api import register_load_control_routes


class FakeLoadControlService:
    def __init__(self) -> None:
        self.calls = []
        self.enabled = False
        self.config = {
            "bound_emonio_device_id": None,
            "bound_actuator_node_id": None,
            "p_reserve": None,
            "operator_limit_a": None,
            "operator_limit_b": None,
            "operator_limit_c": None,
        }
        self.visible = (
            ActuatorDescriptor(
                node_id="ARI-LOAD-MOCK-001",
                location="mock://one",
                device_class="ARI_LOAD_ACTUATOR_MOCK",
                capabilities=("ACTIVE_LOAD_CONTROL",),
                p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
            ),
        )

    def status(self):
        return {
            "stage": "STAGE_1_MOCK_ONLY",
            "mock_only": True,
            "control_mode": "ENABLED" if self.enabled else "DISABLED",
            "config": dict(self.config),
        }

    async def refresh_discovery(self):
        self.calls.append(("refresh_discovery",))
        return self.visible

    def recent_evidence(self, limit=100):
        self.calls.append(("recent_evidence", limit))
        return ({"event": "CONTROL_SERVICE_STARTED"},)

    async def configure_binding(self, *, emonio_device_id, actuator_node_id):
        self.calls.append(("binding", emonio_device_id, actuator_node_id))
        self.config["bound_emonio_device_id"] = emonio_device_id
        self.config["bound_actuator_node_id"] = actuator_node_id

    async def configure_limits(self, **values):
        self.calls.append(("limits", values))
        self.config.update(values)

    async def configure_timing(self, **values):
        self.calls.append(("timing", values))

    async def enable(self):
        self.calls.append(("enable",))
        if self.config["bound_emonio_device_id"] is None:
            raise LoadControlCommandError("SOURCE_UNBOUND")
        self.enabled = True

    async def disable(self):
        self.calls.append(("disable",))
        self.enabled = False


async def _request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = await response.json() if response.content_type == "application/json" else await response.text()
            return response.status, payload


def _app(service):
    app = web.Application()
    app[LOAD_CONTROL_SERVICE_KEY] = service
    register_load_control_routes(app)
    return app


def test_load_control_api_exposes_status_binding_config_timing_and_authority():
    async def scenario():
        service = FakeLoadControlService()
        app = _app(service)

        status, payload = await _request(app, "GET", "/api/v1/load-control/status")
        assert status == 200
        assert payload["mock_only"] is True

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/binding",
            {"emonio_device_id": "emonio-example", "actuator_node_id": "ARI-LOAD-MOCK-001"},
        )
        assert status == 200
        assert payload["config"]["bound_emonio_device_id"] == "emonio-example"

        status, _ = await _request(
            app,
            "POST",
            "/api/v1/load-control/config",
            {
                "p_reserve": 30.0,
                "operator_limit_a": 600.0,
                "operator_limit_b": 700.0,
                "operator_limit_c": 800.0,
            },
        )
        assert status == 200

        status, _ = await _request(
            app,
            "POST",
            "/api/v1/load-control/timing",
            {"control_sample_max_age_s": 2.0, "ack_timeout_s": 1.0},
        )
        assert status == 200

        status, payload = await _request(app, "POST", "/api/v1/load-control/enable", {})
        assert status == 200
        assert payload["control_mode"] == "ENABLED"

        status, payload = await _request(app, "POST", "/api/v1/load-control/disable", {})
        assert status == 200
        assert payload["control_mode"] == "DISABLED"

    asyncio.run(scenario())


def test_load_control_api_preserves_enable_rejection_reason():
    async def scenario():
        service = FakeLoadControlService()
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/enable",
            {},
        )
        assert status == 409
        assert payload == "SOURCE_UNBOUND"

    asyncio.run(scenario())


def test_load_control_api_has_no_direct_phase_power_command_route():
    service = FakeLoadControlService()
    resources = {route.resource.canonical for route in _app(service).router.routes()}
    assert "/api/v1/load-control/command" not in resources
    assert all("p_a" not in path.lower() and "phase-a" not in path.lower() for path in resources)
