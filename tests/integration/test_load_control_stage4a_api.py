import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.load_control.automatic_observation import (
    PControlDecision,
    PControlObserverError,
    PControlObserverState,
    PControlObserverStatus,
)
from emonio_viewer.server.keys import P_CONTROL_OBSERVER_SERVICE_KEY
from emonio_viewer.server.load_control_stage4a_api import register_load_control_stage4a_routes


class FakeObserver:
    def __init__(self) -> None:
        self.configure_calls = []
        self.enable_calls = 0
        self.disable_calls = 0
        self.configure_error = None
        self.enable_error = None
        self.current = _status()
        self.events = (
            SimpleNamespace(
                sequence=7,
                utc="2026-09-02T12:00:00.000Z",
                event="P_OBSERVER_PROPOSAL_CALCULATED",
                line="2026-09-02T12:00:00.000Z  P_OBSERVER_PROPOSAL_CALCULATED",
            ),
        )

    def status(self):
        return self.current

    def configure(self, **kwargs):
        if self.configure_error is not None:
            raise self.configure_error
        self.configure_calls.append(kwargs)
        return self.current

    async def enable(self):
        if self.enable_error is not None:
            raise self.enable_error
        self.enable_calls += 1
        return self.current

    async def disable(self):
        self.disable_calls += 1
        return self.current

    def diagnostics(self, *, after_sequence=0, limit=None):
        values = tuple(item for item in self.events if item.sequence > after_sequence)
        if limit is not None:
            values = values[-limit:]
        return values


def _status() -> PControlObserverStatus:
    return PControlObserverStatus(
        state=PControlObserverState.OBSERVING,
        reason=None,
        source_id="emonio-example",
        phase="A",
        sample_cycle_id=42,
        measured_p_w=-60.0,
        measured_q_var=123.0,
        sample_quality="VALID",
        sample_age_s=0.125,
        p_target_w=0.0,
        p_deadband_w=2.0,
        duty_step_percent=5.0,
        actuator_node_id="ARI-LOAD-001",
        actuator_boot_id="BOOT-1",
        confirmed_command_sequence=10,
        confirmed_requested_duty_percent=25.0,
        confirmed_actual_duty_percent=24.96171516,
        decision=PControlDecision.INCREASE,
        proposed_duty_percent=30.0,
    )


def _app(service=None):
    app = web.Application()
    if service is not None:
        app[P_CONTROL_OBSERVER_SERVICE_KEY] = service
    register_load_control_stage4a_routes(app)
    return app


async def _request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            if body is None:
                response = await client.request(method, path)
            else:
                response = await client.request(method, path, json=body)
            payload = (
                await response.json()
                if response.content_type == "application/json"
                else await response.text()
            )
            return response.status, payload


def test_status_serializes_observer_evidence_without_output_claim() -> None:
    async def scenario() -> None:
        status, payload = await _request(
            _app(FakeObserver()),
            "GET",
            "/api/v1/load-control/p-observer/status",
        )
        assert status == 200
        assert payload == {
            "state": "OBSERVING",
            "reason": None,
            "source_id": "emonio-example",
            "phase": "A",
            "sample_cycle_id": 42,
            "measured_p_w": -60.0,
            "measured_q_var": 123.0,
            "sample_quality": "VALID",
            "sample_age_s": 0.125,
            "p_target_w": 0.0,
            "p_deadband_w": 2.0,
            "duty_step_percent": 5.0,
            "actuator_node_id": "ARI-LOAD-001",
            "actuator_boot_id": "BOOT-1",
            "confirmed_command_sequence": 10,
            "confirmed_requested_duty_percent": 25.0,
            "confirmed_actual_duty_percent": 24.96171516,
            "decision": "INCREASE",
            "proposed_duty_percent": 30.0,
        }

    asyncio.run(scenario())


def test_configure_requires_exact_fields_and_forwards_values_atomically() -> None:
    async def scenario() -> None:
        service = FakeObserver()
        body = {
            "source_id": "emonio-example",
            "phase": "A",
            "p_target_w": 0.0,
            "p_deadband_w": 2.0,
            "duty_step_percent": 5.0,
        }
        status, _payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/p-observer/configure",
            body,
        )
        assert status == 200
        assert service.configure_calls == [body]

        for invalid in (
            {key: value for key, value in body.items() if key != "phase"},
            {**body, "extra": 1},
        ):
            status, _payload = await _request(
                _app(service),
                "POST",
                "/api/v1/load-control/p-observer/configure",
                invalid,
            )
            assert status == 400
        assert service.configure_calls == [body]

    asyncio.run(scenario())


def test_configure_rejects_bad_scalar_types_before_service_call() -> None:
    async def scenario() -> None:
        service = FakeObserver()
        base = {
            "source_id": "emonio-example",
            "phase": "A",
            "p_target_w": 0.0,
            "p_deadband_w": 2.0,
            "duty_step_percent": 5.0,
        }
        for field, value in (
            ("source_id", 3),
            ("phase", "TOTAL"),
            ("p_target_w", "nan"),
            ("p_deadband_w", -1.0),
            ("duty_step_percent", 0.0),
        ):
            status, _payload = await _request(
                _app(service),
                "POST",
                "/api/v1/load-control/p-observer/configure",
                {**base, field: value},
            )
            assert status == 400
        assert service.configure_calls == []

    asyncio.run(scenario())


def test_backend_observer_conflicts_are_http_409() -> None:
    async def scenario() -> None:
        service = FakeObserver()
        service.configure_error = PControlObserverError("OBSERVER_NOT_DISABLED")
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/p-observer/configure",
            {
                "source_id": "emonio-example",
                "phase": "A",
                "p_target_w": 0.0,
                "p_deadband_w": 2.0,
                "duty_step_percent": 5.0,
            },
        )
        assert status == 409
        assert "OBSERVER_NOT_DISABLED" in payload

        service.enable_error = PControlObserverError("CONFIRMED_DUTY_UNKNOWN")
        status, payload = await _request(
            _app(service),
            "POST",
            "/api/v1/load-control/p-observer/enable",
            {},
        )
        assert status == 409
        assert "CONFIRMED_DUTY_UNKNOWN" in payload
        assert service.enable_calls == 0

    asyncio.run(scenario())


def test_enable_and_disable_accept_only_empty_object() -> None:
    async def scenario() -> None:
        service = FakeObserver()
        for path, counter in (
            ("/api/v1/load-control/p-observer/enable", "enable_calls"),
            ("/api/v1/load-control/p-observer/disable", "disable_calls"),
        ):
            status, _payload = await _request(_app(service), "POST", path, {})
            assert status == 200
            assert getattr(service, counter) == 1
            status, _payload = await _request(_app(service), "POST", path, {"x": 1})
            assert status == 400
            assert getattr(service, counter) == 1

    asyncio.run(scenario())


def test_diagnostics_are_read_only_and_sequence_filtered() -> None:
    async def scenario() -> None:
        service = FakeObserver()
        status, payload = await _request(
            _app(service),
            "GET",
            "/api/v1/load-control/p-observer/diagnostics?after_sequence=0",
        )
        assert status == 200
        assert payload == {
            "latest_sequence": 7,
            "events": [
                {
                    "sequence": 7,
                    "utc": "2026-09-02T12:00:00.000Z",
                    "event": "P_OBSERVER_PROPOSAL_CALCULATED",
                    "line": "2026-09-02T12:00:00.000Z  P_OBSERVER_PROPOSAL_CALCULATED",
                }
            ],
        }

        status, payload = await _request(
            _app(service),
            "GET",
            "/api/v1/load-control/p-observer/diagnostics?after_sequence=7",
        )
        assert status == 200
        assert payload == {"latest_sequence": 7, "events": []}

        status, _payload = await _request(
            _app(service),
            "GET",
            "/api/v1/load-control/p-observer/diagnostics?after_sequence=-1",
        )
        assert status == 400

    asyncio.run(scenario())
