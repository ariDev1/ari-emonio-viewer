import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.stage3a import Stage3AError, Stage3AState, Stage3AStatus
from emonio_viewer.server.keys import LOAD_CONTROL_STAGE3A_SERVICE_KEY
from emonio_viewer.server.load_control_api import register_load_control_routes
from emonio_viewer.server.load_control_stage3b_api import register_load_control_stage3b_routes


ONE_A = ThreePhasePower(1.0, 0.0, 0.0)


class FakeStage3BService:
    def __init__(self) -> None:
        self.run_calls = 0
        self.run_error = None
        self.current = Stage3AStatus(
            state=Stage3AState.READY,
            selected_source_id="emonio-example",
            sample_cycle_id=None,
            command_sequence=None,
            ack_result=None,
            rejection_reason=None,
            admissible=True,
        )
        self.stage3b = SimpleNamespace(
            state=Stage3AState.READY,
            selected_source_id="emonio-example",
            sample_cycle_id=None,
            command_sequence=None,
            ack_result=None,
            rejection_reason=None,
            admissible=True,
            safe_reset_required=False,
            fixed_request=ONE_A,
        )

    def status(self):
        return self.current

    def simulated_status(self):
        return self.stage3b

    async def run_simulated_test(self):
        if self.run_error is not None:
            raise self.run_error
        self.run_calls += 1
        self.current = Stage3AStatus(
            state=Stage3AState.PASSED,
            selected_source_id="emonio-example",
            sample_cycle_id=42,
            command_sequence=7,
            ack_result="APPLIED",
            rejection_reason=None,
            admissible=True,
        )
        self.stage3b = SimpleNamespace(
            state=SimpleNamespace(value="RESET_REQUIRED"),
            selected_source_id="emonio-example",
            sample_cycle_id=42,
            command_sequence=7,
            ack_result="APPLIED",
            rejection_reason=None,
            admissible=False,
            safe_reset_required=True,
            fixed_request=ONE_A,
        )
        return self.current


def _app(service=None):
    app = web.Application()
    if service is not None:
        app[LOAD_CONTROL_STAGE3A_SERVICE_KEY] = service
    register_load_control_routes(app)
    register_load_control_stage3b_routes(app)
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


def test_stage3b_status_and_send_routes_are_fixed_and_nonconfigurable() -> None:
    async def scenario() -> None:
        service = FakeStage3BService()
        app = _app(service)

        status, payload = await _request(
            app,
            "GET",
            "/api/v1/load-control/lan-simulated-test/status",
        )
        assert status == 200
        assert payload == {
            "state": "READY",
            "selected_source_id": "emonio-example",
            "sample_cycle_id": None,
            "command_sequence": None,
            "ack_result": None,
            "rejection_reason": None,
            "admissible": True,
            "safe_reset_required": False,
            "fixed_request": {"a": 1.0, "b": 0.0, "c": 0.0},
        }

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-simulated-test/send",
            {},
        )
        assert status == 200
        assert service.run_calls == 1
        assert payload["state"] == "RESET_REQUIRED"
        assert payload["safe_reset_required"] is True
        assert payload["fixed_request"] == {"a": 1.0, "b": 0.0, "c": 0.0}

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-simulated-test/send",
            {"watts": 2.0},
        )
        assert status == 400
        assert "request body must contain exactly no fields" in payload
        assert service.run_calls == 1

    asyncio.run(scenario())


def test_stage3b_send_route_fails_closed_for_nonadmissible_request() -> None:
    async def scenario() -> None:
        service = FakeStage3BService()
        service.run_error = Stage3AError("SAFE_RESET_REQUIRED")

        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/lan-simulated-test/send",
            {},
        )
        assert status == 409
        assert "SAFE_RESET_REQUIRED" in payload
        assert service.run_calls == 0

    asyncio.run(scenario())
