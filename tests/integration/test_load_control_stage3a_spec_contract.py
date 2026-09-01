import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.load_control.stage3a import Stage3AState, Stage3AStatus
from emonio_viewer.server.keys import LOAD_CONTROL_STAGE3A_SERVICE_KEY
from emonio_viewer.server.load_control_api import register_load_control_routes


class FakeStage3AService:
    def __init__(self) -> None:
        self.selected = None
        self.send_calls = 0

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
        return Stage3AStatus(
            state=Stage3AState.READY if self.selected else Stage3AState.IDLE,
            selected_source_id=self.selected,
            sample_cycle_id=None,
            command_sequence=None,
            ack_result=None,
            rejection_reason=None,
            admissible=bool(self.selected),
        )

    async def select_source(self, device_id: str):
        self.selected = device_id
        return self.status()

    async def run_safe_test(self):
        self.send_calls += 1
        return Stage3AStatus(
            state=Stage3AState.PASSED,
            selected_source_id=self.selected,
            sample_cycle_id=42,
            command_sequence=1,
            ack_result="APPLIED",
            rejection_reason=None,
            admissible=True,
        )


def _app(service: FakeStage3AService) -> web.Application:
    app = web.Application()
    app[LOAD_CONTROL_STAGE3A_SERVICE_KEY] = service
    register_load_control_routes(app)
    return app


async def _request(app, method: str, path: str, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = (
                await response.json()
                if response.content_type == "application/json"
                else await response.text()
            )
            return response.status, payload


def test_stage3a_uses_only_approved_lan_safe_test_routes() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        app = _app(service)

        for path in (
            "/api/v1/load-control/lan-safe-test/sources",
            "/api/v1/load-control/lan-safe-test/status",
        ):
            status, _payload = await _request(app, "GET", path)
            assert status == 200

        status, _payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/source",
            {"emonio_device_id": "emonio-example"},
        )
        assert status == 200
        assert service.selected == "emonio-example"

        status, payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/send",
            {},
        )
        assert status == 200
        assert payload["state"] == "PASSED"
        assert service.send_calls == 1

        for method, path in (
            ("GET", "/api/v1/load-control/safe-test/sources"),
            ("GET", "/api/v1/load-control/safe-test/status"),
            ("POST", "/api/v1/load-control/safe-test/source"),
            ("POST", "/api/v1/load-control/safe-test/run"),
        ):
            status, _payload = await _request(app, method, path, {})
            assert status == 404

    asyncio.run(scenario())


def test_stage3a_source_body_accepts_exactly_one_emonio_device_id() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        app = _app(service)

        for body in (
            {},
            {"emonio_device_id": "emonio-example", "extra": True},
            {"emonio_device_id": "emonio-example", "node_id": "override"},
        ):
            status, _payload = await _request(
                app,
                "POST",
                "/api/v1/load-control/lan-safe-test/source",
                body,
            )
            assert status == 400

        assert service.selected is None

    asyncio.run(scenario())


def test_stage3a_send_body_accepts_only_empty_json_object() -> None:
    async def scenario() -> None:
        service = FakeStage3AService()
        app = _app(service)

        forbidden_bodies = (
            {"control_enabled": True},
            {"p_load_request": {"a": 1.0, "b": 0.0, "c": 0.0}},
            {"q_comp_request": {"a": 1.0, "b": 0.0, "c": 0.0}},
            {"sequence": 9},
            {"node_id": "override"},
            {"boot_id": "override"},
            {"measured_p": {"a": 1.0, "b": 2.0, "c": 3.0}},
            {"measurement_cycle_id": 99},
        )
        for body in forbidden_bodies:
            status, _payload = await _request(
                app,
                "POST",
                "/api/v1/load-control/lan-safe-test/send",
                body,
            )
            assert status == 400

        assert service.send_calls == 0

        status, _payload = await _request(
            app,
            "POST",
            "/api/v1/load-control/lan-safe-test/send",
            {},
        )
        assert status == 200
        assert service.send_calls == 1

    asyncio.run(scenario())
