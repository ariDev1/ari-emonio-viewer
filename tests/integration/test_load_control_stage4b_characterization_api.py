import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.characterization import build_characterization_point
from emonio_viewer.load_control.characterization_service import (
    CharacterizationState,
    CharacterizationStatus,
    Stage4BCharacterizationError,
)
from emonio_viewer.server.keys import CHARACTERIZATION_SERVICE_KEY
from emonio_viewer.server.load_control_stage4b_characterization_api import (
    register_load_control_stage4b_characterization_routes,
)


class FakeCharacterizationService:
    def __init__(self) -> None:
        self.manual_calls = []
        self.sweep_calls = []
        self.error = None
        self.current = _status()

    def status(self):
        return self.current

    async def capture_manual(self, *, source_id: str, phase: str):
        if self.error is not None:
            raise self.error
        self.manual_calls.append({"source_id": source_id, "phase": phase})
        return self.current

    async def run_auto_sweep(self, *, source_id: str, phase: str, duties):
        if self.error is not None:
            raise self.error
        self.sweep_calls.append(
            {"source_id": source_id, "phase": phase, "duties": tuple(duties)}
        )
        return self.current


def _status() -> CharacterizationStatus:
    point = build_characterization_point(
        session_id="CHAR-1",
        mode="AUTO_SWEEP",
        source_id="emonio-a",
        phase="A",
        actuator_node_id="ARI-LOAD-001",
        actuator_boot_id="BOOT-1",
        command_sequence=17,
        requested_duty_percent=25.0,
        actual_duty_percent=24.96171516,
        cycle_ids=(3, 4, 5),
        p_samples_w=(-30.0, -29.0, -31.0),
        utc="2026-09-02T14:00:00+00:00",
    )
    return CharacterizationStatus(
        state=CharacterizationState.COMPLETED,
        session_id="CHAR-1",
        mode="AUTO_SWEEP",
        source_id="emonio-a",
        phase="A",
        point_index=1,
        point_count=1,
        current_requested_duty_percent=None,
        settling_cycles_observed=2,
        measured_cycles_observed=3,
        points=(point,),
        last_error=None,
        safe_confirmed=True,
    )


def _app(service=None):
    app = web.Application()
    if service is not None:
        app[CHARACTERIZATION_SERVICE_KEY] = service
    register_load_control_stage4b_characterization_routes(app)
    return app


async def _request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body) if body is not None else await client.request(method, path)
            payload = await response.json() if response.content_type == "application/json" else await response.text()
            return response.status, payload


def test_status_serializes_scientific_characterization_evidence() -> None:
    async def scenario() -> None:
        status, payload = await _request(
            _app(FakeCharacterizationService()),
            "GET",
            "/api/v1/load-control/characterization/status",
        )
        assert status == 200
        assert payload["state"] == "COMPLETED"
        assert payload["safe_confirmed"] is True
        assert payload["points"] == [
            {
                "session_id": "CHAR-1",
                "mode": "AUTO_SWEEP",
                "source_id": "emonio-a",
                "phase": "A",
                "actuator_node_id": "ARI-LOAD-001",
                "actuator_boot_id": "BOOT-1",
                "command_sequence": 17,
                "requested_duty_percent": 25.0,
                "actual_duty_percent": 24.96171516,
                "cycle_ids": [3, 4, 5],
                "p_samples_w": [-30.0, -29.0, -31.0],
                "mean_p_w": -30.0,
                "min_p_w": -31.0,
                "max_p_w": -29.0,
                "sample_stdev_p_w": 1.0,
                "utc": "2026-09-02T14:00:00+00:00",
            }
        ]

    asyncio.run(scenario())


def test_manual_capture_accepts_only_source_and_phase() -> None:
    async def scenario() -> None:
        service = FakeCharacterizationService()
        body = {"source_id": "emonio-a", "phase": "A"}
        status, _ = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/characterization/manual-capture",
            body,
        )
        assert status == 200
        assert service.manual_calls == [body]

        for invalid in (
            {"source_id": "emonio-a"},
            {**body, "extra": 1},
            {"source_id": "emonio-a", "phase": "TOTAL"},
        ):
            status, _ = await _request(
                _app(service),
                "POST",
                "/api/v1/load-control/characterization/manual-capture",
                invalid,
            )
            assert status == 400
        assert service.manual_calls == [body]

    asyncio.run(scenario())


def test_auto_sweep_requires_explicit_numeric_duty_list() -> None:
    async def scenario() -> None:
        service = FakeCharacterizationService()
        body = {"source_id": "emonio-a", "phase": "A", "duties": [25.0, 35.0, 50.0]}
        status, _ = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/characterization/auto-sweep",
            body,
        )
        assert status == 200
        assert service.sweep_calls == [
            {"source_id": "emonio-a", "phase": "A", "duties": (25.0, 35.0, 50.0)}
        ]

        for invalid in (
            {"source_id": "emonio-a", "phase": "A"},
            {**body, "duties": "25,35"},
            {**body, "duties": [25.0, True]},
            {**body, "duties": [25.0, 75.1]},
            {**body, "duties": [25.0, 25.0]},
        ):
            status, _ = await _request(
                _app(service),
                "POST",
                "/api/v1/load-control/characterization/auto-sweep",
                invalid,
            )
            assert status == 400
        assert len(service.sweep_calls) == 1

    asyncio.run(scenario())


def test_service_conflict_is_http_409_and_missing_service_is_503() -> None:
    async def scenario() -> None:
        service = FakeCharacterizationService()
        service.error = Stage4BCharacterizationError("CHARACTERIZATION_ACTIVE")
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/characterization/manual-capture",
            {"source_id": "emonio-a", "phase": "A"},
        )
        assert status == 409
        assert "CHARACTERIZATION_ACTIVE" in payload

        status, payload = await _request(
            _app(),
            "GET",
            "/api/v1/load-control/characterization/status",
        )
        assert status == 503
        assert "CHARACTERIZATION_NOT_AVAILABLE" in payload

    asyncio.run(scenario())
