from __future__ import annotations

import math

from aiohttp import web

from emonio_viewer.load_control.zero_export_service import (
    Stage4CZeroExportControllerError,
    ZeroExportControllerStatus,
)

from .keys import ZERO_EXPORT_CONTROLLER_SERVICE_KEY


_CONFIG_FIELDS = {"source_id", "phase", "p_deadband_w"}


async def _json_object(request: web.Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="INVALID_JSON") from exc
    if type(payload) is not dict:
        raise web.HTTPBadRequest(text="JSON_OBJECT_REQUIRED")
    return payload


def _service(request: web.Request):
    service = request.app.get(ZERO_EXPORT_CONTROLLER_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="ZERO_EXPORT_NOT_AVAILABLE")
    return service


def _status_payload(status: ZeroExportControllerStatus) -> dict:
    return {
        "state": status.state.value,
        "reason": status.reason,
        "source_id": status.source_id,
        "phase": status.phase,
        "p_deadband_w": status.p_deadband_w,
        "sample_cycle_id": status.sample_cycle_id,
        "measured_p_w": status.measured_p_w,
        "sample_quality": status.sample_quality,
        "action": status.action,
        "lower_bracket_duty_percent": status.lower_bracket_duty_percent,
        "upper_bracket_duty_percent": status.upper_bracket_duty_percent,
        "actuator_node_id": status.actuator_node_id,
        "actuator_boot_id": status.actuator_boot_id,
        "command_sequence": status.command_sequence,
        "confirmed_requested_duty_percent": status.confirmed_requested_duty_percent,
        "confirmed_actual_duty_percent": status.confirmed_actual_duty_percent,
        "safe_confirmed": status.safe_confirmed,
    }


def _selection(payload: dict) -> tuple[str, str, float]:
    source_id = payload.get("source_id")
    phase = payload.get("phase")
    deadband = payload.get("p_deadband_w")
    if not isinstance(source_id, str) or not source_id:
        raise web.HTTPBadRequest(text="source_id_INVALID")
    if phase not in {"A", "B", "C"}:
        raise web.HTTPBadRequest(text="phase_INVALID")
    if isinstance(deadband, bool) or not isinstance(deadband, (int, float)):
        raise web.HTTPBadRequest(text="p_deadband_w_INVALID")
    value = float(deadband)
    if not math.isfinite(value) or value < 0.0:
        raise web.HTTPBadRequest(text="p_deadband_w_INVALID")
    return source_id, phase, value


async def _status(request: web.Request) -> web.Response:
    return web.json_response(_status_payload(_service(request).status()))


async def _configure(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if set(payload) != _CONFIG_FIELDS:
        raise web.HTTPBadRequest(text="ZERO_EXPORT_CONFIG_FIELDS_INVALID")
    source_id, phase, deadband = _selection(payload)
    try:
        status = _service(request).configure(
            source_id=source_id,
            phase=phase,
            p_deadband_w=deadband,
        )
    except Stage4CZeroExportControllerError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


async def _enable(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if payload:
        raise web.HTTPBadRequest(text="ZERO_EXPORT_ENABLE_FIELDS_INVALID")
    try:
        status = await _service(request).enable()
    except Stage4CZeroExportControllerError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


async def _disable(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if payload:
        raise web.HTTPBadRequest(text="ZERO_EXPORT_DISABLE_FIELDS_INVALID")
    try:
        status = await _service(request).disable()
    except Stage4CZeroExportControllerError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


def register_load_control_stage4c_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/load-control/zero-export/status", _status)
    app.router.add_post("/api/v1/load-control/zero-export/configure", _configure)
    app.router.add_post("/api/v1/load-control/zero-export/enable", _enable)
    app.router.add_post("/api/v1/load-control/zero-export/disable", _disable)
