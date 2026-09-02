from __future__ import annotations

from aiohttp import web

from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.load_control.stage3b import Stage3BStatus

from .keys import LOAD_CONTROL_STAGE3A_SERVICE_KEY


def register_load_control_stage3b_routes(app: web.Application) -> None:
    app.router.add_get(
        "/api/v1/load-control/lan-simulated-test/status",
        get_simulated_test_status,
    )
    app.router.add_post(
        "/api/v1/load-control/lan-simulated-test/send",
        run_simulated_test,
    )


def _service(request: web.Request):
    service = request.app.get(LOAD_CONTROL_STAGE3A_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="Stage-3B simulated test service is unavailable")
    if not callable(getattr(service, "simulated_status", None)):
        raise web.HTTPServiceUnavailable(text="Stage-3B simulated test service is unavailable")
    if not callable(getattr(service, "run_simulated_test", None)):
        raise web.HTTPServiceUnavailable(text="Stage-3B simulated test service is unavailable")
    return service


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="request body must be a JSON object")
    return body


def _require_empty_body(body: dict) -> None:
    if body:
        raise web.HTTPBadRequest(text="request body must contain exactly no fields")


def _power_json(value) -> dict:
    return {"a": value.a, "b": value.b, "c": value.c}


def _status_json(status: Stage3BStatus) -> dict:
    return {
        "state": status.state.value,
        "selected_source_id": status.selected_source_id,
        "sample_cycle_id": status.sample_cycle_id,
        "command_sequence": status.command_sequence,
        "ack_result": status.ack_result,
        "rejection_reason": status.rejection_reason,
        "admissible": status.admissible,
        "safe_reset_required": status.safe_reset_required,
        "fixed_request": _power_json(status.fixed_request),
    }


async def get_simulated_test_status(request: web.Request) -> web.Response:
    return web.json_response(_status_json(_service(request).simulated_status()))


async def run_simulated_test(request: web.Request) -> web.Response:
    body = await _body(request)
    _require_empty_body(body)
    service = _service(request)
    try:
        await service.run_simulated_test()
    except Stage3AError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_json(service.simulated_status()))
