from __future__ import annotations

import math

from aiohttp import web

from emonio_viewer.load_control.manual_pwm import ManualPwmStatus
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
    app.router.add_get(
        "/api/v1/load-control/lan-pwm/status",
        get_manual_pwm_status,
    )
    app.router.add_post(
        "/api/v1/load-control/lan-pwm/apply",
        apply_manual_pwm,
    )
    app.router.add_post(
        "/api/v1/load-control/lan-pwm/off",
        turn_manual_pwm_off,
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


def _pwm_service(request: web.Request):
    service = request.app.get(LOAD_CONTROL_STAGE3A_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="manual PWM service is unavailable")
    if not callable(getattr(service, "manual_pwm_status", None)):
        raise web.HTTPServiceUnavailable(text="manual PWM service is unavailable")
    if not callable(getattr(service, "run_manual_pwm", None)):
        raise web.HTTPServiceUnavailable(text="manual PWM service is unavailable")
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


def _required_duty_percent(body: dict) -> float:
    if set(body) != {"duty_percent"}:
        raise web.HTTPBadRequest(text="request body must contain exactly duty_percent")
    value = body.get("duty_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise web.HTTPBadRequest(text="duty_percent must be numeric")
    duty = float(value)
    if not math.isfinite(duty) or duty < 0.0 or duty >= 100.0:
        raise web.HTTPBadRequest(text="duty_percent must satisfy 0 <= duty < 100")
    return duty


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


def _pwm_status_json(status: ManualPwmStatus) -> dict:
    return {
        "state": status.state.value,
        "node_id": status.node_id,
        "boot_id": status.boot_id,
        "command_sequence": status.command_sequence,
        "ack_result": status.ack_result,
        "rejection_reason": status.rejection_reason,
        "requested_duty_percent": status.requested_duty_percent,
        "actual_duty_percent": status.actual_duty_percent,
        "compare_ticks": status.compare_ticks,
        "period_ticks": status.period_ticks,
        "admissible": status.admissible,
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


async def get_manual_pwm_status(request: web.Request) -> web.Response:
    return web.json_response(_pwm_status_json(_pwm_service(request).manual_pwm_status()))


async def apply_manual_pwm(request: web.Request) -> web.Response:
    duty_percent = _required_duty_percent(await _body(request))
    service = _pwm_service(request)
    try:
        status = await service.run_manual_pwm(duty_percent)
    except Stage3AError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_pwm_status_json(status))


async def turn_manual_pwm_off(request: web.Request) -> web.Response:
    body = await _body(request)
    _require_empty_body(body)
    service = _pwm_service(request)
    try:
        status = await service.run_manual_pwm(0.0)
    except Stage3AError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_pwm_status_json(status))
