from __future__ import annotations

import math

from aiohttp import web

from emonio_viewer.load_control.automatic_observation import (
    PControlObserverError,
    PControlObserverStatus,
)

from .keys import P_CONTROL_OBSERVER_SERVICE_KEY


_CONFIG_FIELDS = {
    "source_id",
    "phase",
    "p_target_w",
    "p_deadband_w",
    "duty_step_percent",
}


async def _json_object(request: web.Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="INVALID_JSON") from exc
    if type(payload) is not dict:
        raise web.HTTPBadRequest(text="JSON_OBJECT_REQUIRED")
    return payload


def _finite_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise web.HTTPBadRequest(text=f"{name}_INVALID")
    result = float(value)
    if not math.isfinite(result):
        raise web.HTTPBadRequest(text=f"{name}_INVALID")
    return result


def _status_payload(status: PControlObserverStatus) -> dict:
    return {
        "state": status.state.value,
        "reason": status.reason,
        "source_id": status.source_id,
        "phase": status.phase,
        "sample_cycle_id": status.sample_cycle_id,
        "measured_p_w": status.measured_p_w,
        "measured_q_var": status.measured_q_var,
        "sample_quality": status.sample_quality,
        "sample_age_s": status.sample_age_s,
        "p_target_w": status.p_target_w,
        "p_deadband_w": status.p_deadband_w,
        "duty_step_percent": status.duty_step_percent,
        "actuator_node_id": status.actuator_node_id,
        "actuator_boot_id": status.actuator_boot_id,
        "confirmed_command_sequence": status.confirmed_command_sequence,
        "confirmed_requested_duty_percent": status.confirmed_requested_duty_percent,
        "confirmed_actual_duty_percent": status.confirmed_actual_duty_percent,
        "decision": status.decision.value if status.decision is not None else None,
        "proposed_duty_percent": status.proposed_duty_percent,
    }


def _observer(request: web.Request):
    service = request.app.get(P_CONTROL_OBSERVER_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="P_OBSERVER_NOT_AVAILABLE")
    return service


async def _status(request: web.Request) -> web.Response:
    return web.json_response(_status_payload(_observer(request).status()))


async def _configure(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if set(payload) != _CONFIG_FIELDS:
        raise web.HTTPBadRequest(text="CONFIG_FIELDS_INVALID")

    source_id = payload["source_id"]
    phase = payload["phase"]
    if not isinstance(source_id, str) or not source_id:
        raise web.HTTPBadRequest(text="source_id_INVALID")
    if phase not in {"A", "B", "C"}:
        raise web.HTTPBadRequest(text="phase_INVALID")

    target = _finite_number(payload["p_target_w"], "p_target_w")
    deadband = _finite_number(payload["p_deadband_w"], "p_deadband_w")
    step = _finite_number(payload["duty_step_percent"], "duty_step_percent")
    if deadband < 0.0:
        raise web.HTTPBadRequest(text="p_deadband_w_INVALID")
    if step <= 0.0:
        raise web.HTTPBadRequest(text="duty_step_percent_INVALID")

    try:
        status = _observer(request).configure(
            source_id=source_id,
            phase=phase,
            p_target_w=target,
            p_deadband_w=deadband,
            duty_step_percent=step,
        )
    except PControlObserverError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


async def _empty_command(request: web.Request, method_name: str) -> web.Response:
    payload = await _json_object(request)
    if payload:
        raise web.HTTPBadRequest(text="EMPTY_OBJECT_REQUIRED")
    try:
        status = await getattr(_observer(request), method_name)()
    except PControlObserverError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


async def _enable(request: web.Request) -> web.Response:
    return await _empty_command(request, "enable")


async def _disable(request: web.Request) -> web.Response:
    return await _empty_command(request, "disable")


def _after_sequence(request: web.Request) -> int:
    raw = request.query.get("after_sequence", "0")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="after_sequence_INVALID") from exc
    if value < 0 or str(value) != raw.strip():
        raise web.HTTPBadRequest(text="after_sequence_INVALID")
    return value


async def _diagnostics(request: web.Request) -> web.Response:
    service = _observer(request)
    after_sequence = _after_sequence(request)
    all_events = service.diagnostics(after_sequence=0)
    latest_sequence = max((item.sequence for item in all_events), default=0)
    events = service.diagnostics(after_sequence=after_sequence)
    return web.json_response(
        {
            "latest_sequence": latest_sequence,
            "events": [
                {
                    "sequence": item.sequence,
                    "utc": item.utc,
                    "event": item.event,
                    "line": item.line,
                }
                for item in events
            ],
        }
    )


def register_load_control_stage4a_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/load-control/p-observer/status", _status)
    app.router.add_post("/api/v1/load-control/p-observer/configure", _configure)
    app.router.add_post("/api/v1/load-control/p-observer/enable", _enable)
    app.router.add_post("/api/v1/load-control/p-observer/disable", _disable)
    app.router.add_get("/api/v1/load-control/p-observer/diagnostics", _diagnostics)
