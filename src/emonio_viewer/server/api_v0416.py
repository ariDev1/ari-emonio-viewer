from datetime import datetime, timezone
import math

from aiohttp import web

from emonio_viewer.lifecycle.model import DeviceLifecycleCommandError
from emonio_viewer.recording.negative_monitor import (
    MonitorPhase,
    NegativeCondition,
    NegativeMonitorConfig,
)

from .api import (
    _body,
    _device_config,
    _lifecycle_service,
    _recording,
    _require_device_id,
    _validate_recording_interval_for_device,
    change_recording_interval,
    connect_device,
    get_ct_configuration,
    get_device,
    get_devices,
    get_diagnostics,
    get_modbus_evidence,
    get_runtime_config,
    get_scope_status,
    hold_scope,
    live_scope,
    read_ct_configuration,
    read_modbus_evidence,
    reconnect_device,
    start_recording,
    start_scope,
    stop_recording,
    stop_scope,
)


def register_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/devices", get_devices)
    app.router.add_get("/api/v1/devices/{device_id}", get_device)
    app.router.add_get("/api/v1/diagnostics/{device_id}", get_diagnostics)
    app.router.add_get("/api/v1/config/runtime", get_runtime_config)
    app.router.add_get("/api/v1/devices/{device_id}/ct-config", get_ct_configuration)
    app.router.add_get("/api/v1/devices/{device_id}/modbus-evidence", get_modbus_evidence)
    app.router.add_post("/api/v1/devices/{device_id}/modbus-evidence/read", read_modbus_evidence)
    app.router.add_post("/api/v1/devices/{device_id}/ct-config/read", read_ct_configuration)
    app.router.add_post("/api/v1/devices/{device_id}/disconnect", disconnect_device)
    app.router.add_post("/api/v1/devices/{device_id}/reconnect", reconnect_device)
    app.router.add_post("/api/v1/devices/connect", connect_device)
    app.router.add_get("/api/v1/recording/status", get_recording_status)
    app.router.add_post("/api/v1/recording/start", start_recording)
    app.router.add_post("/api/v1/recording/stop", stop_recording)
    app.router.add_post("/api/v1/recording/interval", change_recording_interval)
    app.router.add_post("/api/v1/recording/monitor/configure", configure_recording_monitor)
    app.router.add_post("/api/v1/recording/monitor/enable", enable_recording_monitor)
    app.router.add_post("/api/v1/recording/monitor/disable", disable_recording_monitor)
    app.router.add_get("/api/v1/devices/{device_id}/scope", get_scope_status)
    app.router.add_post("/api/v1/devices/{device_id}/scope/start", start_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/hold", hold_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/live", live_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/stop", stop_scope)


def _monitor_config(request, body: dict) -> NegativeMonitorConfig:
    device_id = _require_device_id(request, body)
    try:
        condition = NegativeCondition(body.get("condition"))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid monitor condition") from exc

    phase_values = body.get("phases")
    if not isinstance(phase_values, list):
        raise web.HTTPBadRequest(text="phases must be a list")
    if not phase_values:
        raise web.HTTPBadRequest(text="at least one monitor phase is required")
    try:
        phases = tuple(MonitorPhase(value) for value in phase_values)
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid monitor phase") from exc
    if len(set(phases)) != len(phases):
        raise web.HTTPBadRequest(text="monitor phases must be unique")

    try:
        interval = float(body["recording_interval_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="recording_interval_s must be numeric") from exc
    if not math.isfinite(interval):
        raise web.HTTPBadRequest(text="recording_interval_s must be finite")
    if interval <= 0:
        raise web.HTTPBadRequest(text="recording_interval_s must be > 0")
    _validate_recording_interval_for_device(request, device_id, interval)

    try:
        return NegativeMonitorConfig(
            device_id=device_id,
            condition=condition,
            phases=phases,
            recording_interval_s=interval,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


def _monitor_command_result(call):
    try:
        return call()
    except KeyError as exc:
        raise web.HTTPNotFound(text="unknown device_id") from exc
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    except RuntimeError as exc:
        if str(exc) == "recording commands disabled":
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
        raise web.HTTPConflict(text=str(exc)) from exc


async def get_recording_status(request):
    recording = _recording(request)
    return web.json_response(
        {
            "active": list(recording.active_recordings()),
            "errors": list(recording.recording_failures()),
            "monitors": list(recording.monitor_statuses()),
        }
    )


async def configure_recording_monitor(request):
    body = await _body(request)
    config = _monitor_config(request, body)
    status = _monitor_command_result(lambda: _recording(request).configure_monitor(config))
    return web.json_response(status)


async def enable_recording_monitor(request):
    body = await _body(request)
    device_id = _require_device_id(request, body)
    status = _monitor_command_result(lambda: _recording(request).enable_monitor(device_id))
    return web.json_response(status)


async def disable_recording_monitor(request):
    body = await _body(request)
    device_id = _require_device_id(request, body)
    status = _monitor_command_result(lambda: _recording(request).disable_monitor(device_id))
    return web.json_response(status)


async def disconnect_device(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _lifecycle_service(request)
    try:
        result = await service.disconnect(device_id)
    except DeviceLifecycleCommandError as exc:
        return web.json_response(
            exc.result.as_dict(),
            status=409 if exc.conflict else 502,
        )
    _recording(request).note_device_disconnect(device_id, datetime.now(timezone.utc))
    return web.json_response(result.as_dict())
