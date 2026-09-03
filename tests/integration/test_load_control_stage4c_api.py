import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.zero_export_service import (
    Stage4CZeroExportControllerError,
    ZeroExportControllerState,
    ZeroExportControllerStatus,
)
from emonio_viewer.server.keys import ZERO_EXPORT_CONTROLLER_SERVICE_KEY
from emonio_viewer.server.load_control_stage4c_api import register_load_control_stage4c_routes


class FakeZeroExportService:
    def __init__(self) -> None:
        self.configure_calls = []
        self.enable_calls = 0
        self.disable_calls = 0
        self.error = None
        self.current = _status()

    def status(self):
        return self.current

    def configure(self, *, source_id: str, phase: str, p_deadband_w: float):
        if self.error is not None:
            raise self.error
        self.configure_calls.append(
            {"source_id": source_id, "phase": phase, "p_deadband_w": p_deadband_w}
        )
        return self.current

    async def enable(self):
        if self.error is not None:
            raise self.error
        self.enable_calls += 1
        return self.current

    async def disable(self):
        if self.error is not None:
            raise self.error
        self.disable_calls += 1
        return self.current


def _status() -> ZeroExportControllerStatus:
    return ZeroExportControllerStatus(
        state=ZeroExportControllerState.TARGET_BAND,
        reason=None,
        source_id="emonio-a",
        phase="A",
        p_deadband_w=2.0,
        sample_cycle_id=44,
        measured_p_w=-0.8,
        sample_quality="VALID",
        action="HOLD",
        lower_bracket_duty_percent=50.0,
        upper_bracket_duty_percent=62.5,
        actuator_node_id="ARI-LOAD-001",
        actuator_boot_id="BOOT-1",
        command_sequence=21,
        confirmed_requested_duty_percent=56.25,
        confirmed_actual_duty_percent=56.20214395,
        confirmed_compare_ticks=367,
        confirmed_period_ticks=653,
        safe_confirmed=False,
    )


def _app(service=None):
    app = web.Application()
    if service is not None:
        app[ZERO_EXPORT_CONTROLLER_SERVICE_KEY] = service
    register_load_control_stage4c_routes(app)
    return app


async def _request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = (
                await client.request(method, path, json=body)
                if body is not None
                else await client.request(method, path)
            )
            payload = (
                await response.json()
                if response.content_type == "application/json"
                else await response.text()
            )
            return response.status, payload


def test_status_serializes_zero_export_evidence() -> None:
    async def scenario() -> None:
        status, payload = await _request(
            _app(FakeZeroExportService()),
            "GET",
            "/api/v1/load-control/zero-export/status",
        )
        assert status == 200
        assert payload == {
            "state": "TARGET_BAND",
            "reason": None,
            "source_id": "emonio-a",
            "phase": "A",
            "p_deadband_w": 2.0,
            "sample_cycle_id": 44,
            "measured_p_w": -0.8,
            "sample_quality": "VALID",
            "action": "HOLD",
            "lower_bracket_duty_percent": 50.0,
            "upper_bracket_duty_percent": 62.5,
            "actuator_node_id": "ARI-LOAD-001",
            "actuator_boot_id": "BOOT-1",
            "command_sequence": 21,
            "confirmed_requested_duty_percent": 56.25,
            "confirmed_actual_duty_percent": 56.20214395,
            "confirmed_compare_ticks": 367,
            "confirmed_period_ticks": 653,
            "safe_confirmed": False,
        }

    asyncio.run(scenario())


def test_configure_requires_exact_source_phase_and_deadband_fields() -> None:
    async def scenario() -> None:
        service = FakeZeroExportService()
        body = {"source_id": "emonio-a", "phase": "A", "p_deadband_w": 2.0}
        status, _ = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/zero-export/configure",
            body,
        )
        assert status == 200
        assert service.configure_calls == [body]

        for invalid in (
            {"source_id": "emonio-a", "phase": "A"},
            {**body, "extra": 1},
            {**body, "phase": "TOTAL"},
            {**body, "p_deadband_w": -1.0},
            {**body, "p_deadband_w": True},
        ):
            status, _ = await _request(
                _app(service),
                "POST",
                "/api/v1/load-control/zero-export/configure",
                invalid,
            )
            assert status == 400
        assert service.configure_calls == [body]

    asyncio.run(scenario())


def test_enable_and_disable_require_empty_objects() -> None:
    async def scenario() -> None:
        service = FakeZeroExportService()
        for path, attribute in (
            ("/api/v1/load-control/zero-export/enable", "enable_calls"),
            ("/api/v1/load-control/zero-export/disable", "disable_calls"),
        ):
            status, _ = await _request(_app(service), "POST", path, {})
            assert status == 200
            assert getattr(service, attribute) == 1
            status, _ = await _request(_app(service), "POST", path, {"extra": 1})
            assert status == 400
            assert getattr(service, attribute) == 1

    asyncio.run(scenario())


def test_service_conflict_is_409_and_missing_service_is_503() -> None:
    async def scenario() -> None:
        service = FakeZeroExportService()
        service.error = Stage4CZeroExportControllerError("PWM_OWNER_RESERVED")
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/zero-export/enable",
            {},
        )
        assert status == 409
        assert "PWM_OWNER_RESERVED" in payload

        status, payload = await _request(
            _app(),
            "GET",
            "/api/v1/load-control/zero-export/status",
        )
        assert status == 503
        assert "ZERO_EXPORT_NOT_AVAILABLE" in payload

    asyncio.run(scenario())
