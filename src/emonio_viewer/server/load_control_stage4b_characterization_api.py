from __future__ import annotations

import math

from aiohttp import web

from emonio_viewer.load_control.characterization import validate_sweep_duties
from emonio_viewer.load_control.characterization_service import (
    CharacterizationStatus,
    Stage4BCharacterizationError,
)

from .keys import CHARACTERIZATION_SERVICE_KEY


_MANUAL_FIELDS = {"source_id", "phase"}
_SWEEP_FIELDS = {"source_id", "phase", "duties"}


async def _json_object(request: web.Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="INVALID_JSON") from exc
    if type(payload) is not dict:
        raise web.HTTPBadRequest(text="JSON_OBJECT_REQUIRED")
    return payload


def _selection(payload: dict) -> tuple[str, str]:
    source_id = payload.get("source_id")
    phase = payload.get("phase")
    if not isinstance(source_id, str) or not source_id:
        raise web.HTTPBadRequest(text="source_id_INVALID")
    if phase not in {"A", "B", "C"}:
        raise web.HTTPBadRequest(text="phase_INVALID")
    return source_id, phase


def _point_payload(point) -> dict:
    return {
        "session_id": point.session_id,
        "mode": point.mode,
        "source_id": point.source_id,
        "phase": point.phase,
        "actuator_node_id": point.actuator_node_id,
        "actuator_boot_id": point.actuator_boot_id,
        "command_sequence": point.command_sequence,
        "requested_duty_percent": point.requested_duty_percent,
        "actual_duty_percent": point.actual_duty_percent,
        "cycle_ids": list(point.cycle_ids),
        "p_samples_w": list(point.p_samples_w),
        "mean_p_w": point.mean_p_w,
        "min_p_w": point.min_p_w,
        "max_p_w": point.max_p_w,
        "sample_stdev_p_w": point.sample_stdev_p_w,
        "utc": point.utc,
    }


def _status_payload(status: CharacterizationStatus) -> dict:
    return {
        "state": status.state.value,
        "session_id": status.session_id,
        "mode": status.mode,
        "source_id": status.source_id,
        "phase": status.phase,
        "point_index": status.point_index,
        "point_count": status.point_count,
        "current_requested_duty_percent": status.current_requested_duty_percent,
        "settling_cycles_observed": status.settling_cycles_observed,
        "measured_cycles_observed": status.measured_cycles_observed,
        "points": [_point_payload(point) for point in status.points],
        "last_error": status.last_error,
        "safe_confirmed": status.safe_confirmed,
    }


def _service(request: web.Request):
    service = request.app.get(CHARACTERIZATION_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="CHARACTERIZATION_NOT_AVAILABLE")
    return service


async def _status(request: web.Request) -> web.Response:
    return web.json_response(_status_payload(_service(request).status()))


async def _manual_capture(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if set(payload) != _MANUAL_FIELDS:
        raise web.HTTPBadRequest(text="MANUAL_CAPTURE_FIELDS_INVALID")
    source_id, phase = _selection(payload)
    try:
        status = await _service(request).capture_manual(source_id=source_id, phase=phase)
    except Stage4BCharacterizationError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


def _duties(payload: dict) -> tuple[float, ...]:
    raw = payload.get("duties")
    if type(raw) is not list:
        raise web.HTTPBadRequest(text="duties_INVALID")
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise web.HTTPBadRequest(text="duties_INVALID")
        value = float(item)
        if not math.isfinite(value):
            raise web.HTTPBadRequest(text="duties_INVALID")
        values.append(value)
    try:
        return validate_sweep_duties(values)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="duties_INVALID") from exc


async def _auto_sweep(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    if set(payload) != _SWEEP_FIELDS:
        raise web.HTTPBadRequest(text="AUTO_SWEEP_FIELDS_INVALID")
    source_id, phase = _selection(payload)
    duties = _duties(payload)
    try:
        status = await _service(request).run_auto_sweep(
            source_id=source_id,
            phase=phase,
            duties=duties,
        )
    except Stage4BCharacterizationError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_status_payload(status))


def register_load_control_stage4b_characterization_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/load-control/characterization/status", _status)
    app.router.add_post(
        "/api/v1/load-control/characterization/manual-capture",
        _manual_capture,
    )
    app.router.add_post(
        "/api/v1/load-control/characterization/auto-sweep",
        _auto_sweep,
    )
