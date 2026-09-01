import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.load_control.stage3a import Stage3AError, Stage3AState, Stage3AStatus
from emonio_viewer.server.keys import LOAD_CONTROL_STAGE3A_SERVICE_KEY
from emonio_viewer.server.load_control_api import register_load_control_routes


class FakeStage3AService:
    def __init__(self) -> None:
        self.selected = None
        self.run_calls = 0
        self.select_error = None
        self.run_error = None
        self.current = Stage3AStatus(
            state=Stage3AState.IDLE,
            selected_source_id=None,
            sample_cycle_id=None,
            command_sequence=None,
            ack_result=None,
            rejection_reason=None,
            admissible=False,
        )

    def sources(self):
        return (
            DeviceConfig(
                id="emonio-example",
                name="Emonio Example",
                host="192.0.2.11",
                poll_interval_s=2.0,
                timeout_s=0.5,
            ),
        )

    def status(self):
        return self.current

    async def select_source(self, device_id: str):
        if self.select_error is not None:
            raise self.select_error
        self.selected = device_id
        self.current = Stage3AStatus(
            state=Stage3AState.READY,
            selected_source_id=device_id,
            sample_cycle_id=None,
            command_sequence=None,
            ack_result=None,
            rejection_reason=None,
            admissible=True,
        )
        return self.current

    async def run_safe_test(self):
        if self.run_error is not None:
            raise self.run_error
        self.run_calls += 1
        self.current = Stage3AStatus(
            state=Stage3AState.PASSED,
            selected_source_id=self.selected,
            sample_cycle_id=42,
            command_sequence=7,
            ack_result="APPLIED",
            rejection_reason=None,
            admissible=True,
        )
        return self.current


def _app(service=None):
    app = web.Application()
    if service is not None:
        app[LOAD_CONTROL_STAGE3A_SERVICE_KEY] = service
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


def test_stage3a_safe_test_sources_status_select_and_run_routes() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        app = _app(service)

        status, payload = await _request(
            app,
            "GET",
            "/api/v1/load-control/lan-safe-test/sources",
        )
        assert status == 200
        assert payload == [
            {
                "device_id": "emonio-example",
                "name": "Emonio Example",
                "poll_interval_s": 2.0,
            }
        ]

        status, payload = await _request(
            app,
            "GET",
            "/api/v1/load-control/lan-safe-test/status",
        )
        assert status == 200
        assert payload == {
            "state": "IDLE",
            "selected_source_id": None,
            "sample_cycle_id": None,
            "command_sequence": None,
            "ack_result": None,
            "rejection_reason": None,
            "admissible": False,
        }

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/source",
            {"emonio_device_id": "emonio-example"},
        )
        assert status == 200
        assert service.selected == "emonio-example"
        assert payload["state"] == "READY"
        assert payload["selected_source_id"] == "emonio-example"
        assert payload["admissible"] is True

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/send",
            {},
        )
        assert status == 200
        assert service.run_calls == 1
        assert payload == {
            "state": "PASSED",
            "selected_source_id": "emonio-example",
            "sample_cycle_id": 42,
            "command_sequence": 7,
            "ack_result": "APPLIED",
            "rejection_reason": None,
            "admissible": True,
        }

    asyncio.run(scenario())


def test_stage3a_safe_test_routes_fail_closed_for_invalid_requests() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        app = _app(service)

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/source",
            {},
        )
        assert status == 400
        assert "request body must contain exactly emonio_device_id" in payload

        service.select_error = Stage3AError("SOURCE_NOT_AVAILABLE")
        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/source",
            {"emonio_device_id": "missing"},
        )
        assert status == 409
        assert "SOURCE_NOT_AVAILABLE" in payload

        service.run_error = Stage3AError("ACTUATOR_NOT_QUALIFIED")
        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/send",
            {},
        )
        assert status == 409
        assert "ACTUATOR_NOT_QUALIFIED" in payload
        assert service.run_calls == 0

        status, payload = await _request(
            _app(),
            "GET",
            "/api/v1/load-control/lan-safe-test/status",
        )
        assert status == 503
        assert "Stage-3A SAFE test service is unavailable" in payload

    asyncio.run(scenario())


def test_stage3a_rejected_exchange_is_a_reported_test_result_not_an_http_transport_error() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        service.current = Stage3AStatus(
            state=Stage3AState.REJECTED,
            selected_source_id="emonio-example",
            sample_cycle_id=43,
            command_sequence=8,
            ack_result=None,
            rejection_reason="ACK_TIMEOUT",
            admissible=True,
        )

        async def rejected_run():
            service.run_calls += 1
            return service.current

        service.run_safe_test = rejected_run
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/lan-safe-test/send",
            {},
        )

        assert status == 200
        assert service.run_calls == 1
        assert payload["state"] == "REJECTED"
        assert payload["rejection_reason"] == "ACK_TIMEOUT"
        assert payload["command_sequence"] == 8

    asyncio.run(scenario())
