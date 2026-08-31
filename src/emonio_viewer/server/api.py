import math
from aiohttp import web

from emonio_viewer.acquisition.connector import TargetConnectionError
from emonio_viewer.acquisition.target import TargetInputError
from emonio_viewer.device_evidence.telnet import CtConfigurationReadError
from emonio_viewer.lifecycle.model import DeviceLifecycleCommandError
from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.modbus.register_map import REGISTER_MAP_ID
from emonio_viewer.scope.service import ScopeServiceError, ScopeSessionConflict

from .keys import (
    CT_CONFIGURATION_SERVICE_KEY,
    DEVICE_CONNECTOR_KEY,
    DEVICE_LIFECYCLE_SERVICE_KEY,
    EVENT_BUS_KEY,
    MODBUS_DEVICE_EVIDENCE_SERVICE_KEY,
    RECORDING_MANAGER_KEY,
    RUNTIME_CONFIG_KEY,
    RUNTIME_STORE_KEY,
    SCOPE_SERVICE_KEY,
)


def block_to_json(block) -> dict:
    measurement = block.measurement
    return {
        "vrms": measurement.vrms,
        "irms": measurement.irms,
        "p": measurement.p,
        "q": measurement.q,
        "s": measurement.s,
        "frequency": measurement.frequency,
        "energy": measurement.energy,
        "pf": measurement.pf,
        "quadrant": block.quadrant.value,
        "flow": block.flow.value,
        "acquired_utc": block.acquired_utc.isoformat(),
    }


def sample_to_json(
    sample: MeasurementSample,
    snapshot,
    *,
    acquisition_state: str | None = None,
) -> dict:
    return {
        "schema_version": sample.identity.schema_version,
        "event": "measurement",
        "device_id": sample.identity.device_id,
        "device_name": sample.identity.device_name,
        "device_ip": sample.identity.device_ip,
        "firmware_version": sample.identity.firmware_version,
        "transport": sample.identity.transport,
        "state": snapshot.state.value,
        "acquisition_state": acquisition_state,
        "sample_age_s": snapshot.sample_age_s,
        "quality": sample.quality.value,
        "warnings": list(sample.warnings),
        "sample": {
            "cycle_id": sample.identity.cycle_id,
            "cycle_started_utc": sample.timing.cycle_started_utc.isoformat(),
            "cycle_finished_utc": sample.timing.cycle_finished_utc.isoformat(),
            "cycle_span_ms": sample.timing.cycle_span_ms,
            "schedule_lag_ms": sample.acquisition.schedule_lag_ms,
            "phase_a": block_to_json(sample.phase_a),
            "phase_b": block_to_json(sample.phase_b),
            "phase_c": block_to_json(sample.phase_c),
            "total": block_to_json(sample.total),
            "derived": {
                "sum_p": sample.derived.sum_p,
                "sum_q": sample.derived.sum_q,
                "sum_s": sample.derived.sum_s,
                "delta_p": sample.derived.delta_p,
                "delta_q": sample.derived.delta_q,
                "delta_s": sample.derived.delta_s,
            },
        },
    }


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
    app.router.add_get("/api/v1/devices/{device_id}/scope", get_scope_status)
    app.router.add_post("/api/v1/devices/{device_id}/scope/start", start_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/hold", hold_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/live", live_scope)
    app.router.add_post("/api/v1/devices/{device_id}/scope/stop", stop_scope)


def _store(request):
    return request.app[RUNTIME_STORE_KEY]


def _recording(request):
    return request.app[RECORDING_MANAGER_KEY]


def _connector(request):
    return request.app.get(DEVICE_CONNECTOR_KEY)


def _lifecycle_service(request):
    service = request.app.get(DEVICE_LIFECYCLE_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="device lifecycle service is unavailable")
    return service


def _acquisition_state(request, device_id: str) -> str | None:
    service = request.app.get(DEVICE_LIFECYCLE_SERVICE_KEY)
    if service is None:
        return None
    return service.status(device_id).acquisition_state


def _ct_configuration(request):
    service = request.app.get(CT_CONFIGURATION_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="CT configuration evidence service is unavailable")
    return service


def _modbus_evidence(request):
    service = request.app.get(MODBUS_DEVICE_EVIDENCE_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="Modbus device evidence service is unavailable")
    return service


def _scope_service(request):
    service = request.app.get(SCOPE_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="scope service is unavailable")
    return service


def _scope_status_json(service, status):
    payload = status.as_dict()
    active_statuses = getattr(service, "active_statuses", lambda: ())()
    payload["active_sessions"] = [
        {"device_id": item.device_id, "state": item.state.value}
        for item in active_statuses
    ]
    return web.json_response(payload)


def _all_device_configs(request):
    connector = _connector(request)
    if connector is not None:
        return connector.device_configs()
    return request.app[RUNTIME_CONFIG_KEY].devices


def _configured_device_ids(request) -> set[str]:
    return {device.id for device in _all_device_configs(request)}


def _require_device_id(request, body: dict) -> str:
    device_id = body.get("device_id")
    if not isinstance(device_id, str) or not device_id:
        raise web.HTTPBadRequest(text="device_id is required")
    if device_id not in _configured_device_ids(request):
        raise web.HTTPNotFound(text="unknown device_id")
    return device_id


async def get_devices(request):
    payload = []
    for snapshot in _store(request).list_devices():
        sample = snapshot.last_sample
        payload.append(
            {
                "device_id": snapshot.device_id,
                "state": snapshot.state.value,
                "acquisition_state": _acquisition_state(request, snapshot.device_id),
                "sample_age_s": snapshot.sample_age_s,
                "transport": None if sample is None else sample.identity.transport,
                "quality": None if sample is None else sample.quality.value,
            }
        )
    return web.json_response(payload)


async def get_device(request):
    try:
        snapshot = _store(request).get_device(request.match_info["device_id"])
    except KeyError as exc:
        raise web.HTTPNotFound() from exc
    acquisition_state = _acquisition_state(request, snapshot.device_id)
    if snapshot.last_sample is None:
        return web.json_response(
            {
                "device_id": snapshot.device_id,
                "state": snapshot.state.value,
                "acquisition_state": acquisition_state,
                "sample": None,
            }
        )
    return web.json_response(
        sample_to_json(
            snapshot.last_sample,
            snapshot,
            acquisition_state=acquisition_state,
        )
    )


async def get_diagnostics(request):
    try:
        snapshot = _store(request).get_device(request.match_info["device_id"])
    except KeyError as exc:
        raise web.HTTPNotFound() from exc
    metrics = snapshot.metrics
    device = _device_config(request, snapshot.device_id)
    payload = {name: getattr(metrics, name) for name in metrics.__dataclass_fields__}
    payload.update(
        {
            "device_id": snapshot.device_id,
            "state": snapshot.state.value,
            "acquisition_state": _acquisition_state(request, snapshot.device_id),
            "sample_age_s": snapshot.sample_age_s,
            "firmware_version": device.firmware_version,
            "register_map_id": REGISTER_MAP_ID,
            "event_deliveries_dropped": request.app[EVENT_BUS_KEY].dropped_deliveries(
                snapshot.device_id
            ),
        }
    )
    return web.json_response(payload)


async def get_runtime_config(request):
    config = request.app[RUNTIME_CONFIG_KEY]
    return web.json_response(
        {
            "default_device": config.viewer.default_device,
            "recording_default_interval_s": config.recording.default_interval_s,
            "devices": [
                {
                    "id": device.id,
                    "name": device.name,
                    "host": device.host,
                    "port": device.port,
                    "unit_id": device.unit_id,
                    "poll_interval_s": device.poll_interval_s,
                    "timeout_s": device.timeout_s,
                    "enabled": device.enabled,
                    "firmware_version": device.firmware_version,
                }
                for device in _all_device_configs(request)
            ],
        }
    )


async def _body(request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="invalid JSON") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON body must be an object")
    return body


def _positive_interval(body: dict) -> float:
    try:
        value = float(body["interval_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="interval_s must be numeric") from exc
    if not math.isfinite(value):
        raise web.HTTPBadRequest(text="interval_s must be finite")
    if value <= 0:
        raise web.HTTPBadRequest(text="interval_s must be > 0")
    return value


def _device_config(request, device_id: str):
    for device in _all_device_configs(request):
        if device.id == device_id:
            return device
    raise web.HTTPNotFound(text="unknown device_id")


def _validate_recording_interval_for_device(request, device_id: str, interval_s: float) -> None:
    device = _device_config(request, device_id)
    if interval_s < device.poll_interval_s:
        raise web.HTTPBadRequest(
            text=(
                "recording interval must be greater than or equal to acquisition interval "
                f"({device.poll_interval_s:g} s)"
            )
        )


async def get_ct_configuration(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    evidence = _ct_configuration(request).get(device_id)
    if evidence is None:
        return web.json_response(
            {"device_id": device_id, "status": "NOT_READ", "evidence": None}
        )
    return web.json_response(
        {"device_id": device_id, "status": "OBSERVED", "evidence": evidence.as_dict()}
    )


async def get_modbus_evidence(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    evidence = _modbus_evidence(request).get(device_id)
    if evidence is None:
        return web.json_response(
            {"device_id": device_id, "status": "NOT_READ", "evidence": None}
        )
    return web.json_response(
        {"device_id": device_id, "status": evidence.read_status, "evidence": evidence.as_dict()}
    )


async def read_modbus_evidence(request):
    device_id = request.match_info["device_id"]
    device = _device_config(request, device_id)
    evidence = await _modbus_evidence(request).read(device)
    return web.json_response(
        {"device_id": device_id, "status": evidence.read_status, "evidence": evidence.as_dict()}
    )


async def read_ct_configuration(request):
    device_id = request.match_info["device_id"]
    device = _device_config(request, device_id)
    body = await _body(request)
    password = body.pop("password", None)
    if not isinstance(password, str) or not password:
        raise web.HTTPBadRequest(text="password is required")
    try:
        evidence = await _ct_configuration(request).read(device.id, device.host, password)
    except CtConfigurationReadError as exc:
        http_status = {
            "TELNET_UNAVAILABLE": 503,
            "AUTH_FAILED": 401,
        }.get(exc.state, 502)
        return web.json_response(
            {
                "status": exc.state,
                "stage": exc.stage,
                "message": exc.user_message,
            },
            status=http_status,
        )
    finally:
        password = ""
        body.clear()
    return web.json_response(
        {"device_id": device_id, "status": "OBSERVED", "evidence": evidence.as_dict()}
    )


async def disconnect_device(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _lifecycle_service(request)
    try:
        result = await service.disconnect(device_id)
    except DeviceLifecycleCommandError as exc:
        return web.json_response(exc.result.as_dict(), status=409 if exc.conflict else 502)
    return web.json_response(result.as_dict())


async def reconnect_device(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _lifecycle_service(request)
    try:
        result = await service.reconnect(device_id)
    except DeviceLifecycleCommandError as exc:
        return web.json_response(exc.result.as_dict(), status=409 if exc.conflict else 502)
    return web.json_response(result.as_dict())


async def connect_device(request):
    connector = _connector(request)
    if connector is None:
        raise web.HTTPServiceUnavailable(text="runtime device connection is unavailable")
    body = await _body(request)
    target = body.get("target")
    if not isinstance(target, str):
        raise web.HTTPBadRequest(text="target must be text")
    try:
        result = await connector.connect(target)
    except TargetInputError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    except TargetConnectionError as exc:
        return web.json_response(
            {
                "state": "TARGET_UNAVAILABLE",
                "message": "Target could not be qualified.",
                "detail": str(exc),
            },
            status=502,
        )

    device = result.device
    try:
        measurement_state = _store(request).get_device(device.id).state.value
    except KeyError:
        measurement_state = None
    return web.json_response(
        {
            "state": "EXISTING" if result.already_connected else "CONNECTED",
            "device_id": device.id,
            "name": device.name,
            "host": device.host,
            "poll_interval_s": device.poll_interval_s,
            "firmware_version": device.firmware_version,
            "already_connected": result.already_connected,
            "acquisition_state": _acquisition_state(request, device.id),
            "measurement_state": measurement_state,
        }
    )


async def get_recording_status(request):
    recording = _recording(request)
    return web.json_response(
        {
            "active": list(recording.active_recordings()),
            "errors": list(recording.recording_failures()),
        }
    )


async def start_recording(request):
    body = await _body(request)
    interval = _positive_interval(body)
    device_id = _require_device_id(request, body)
    _validate_recording_interval_for_device(request, device_id, interval)
    note = body.get("session_note", "")
    if not isinstance(note, str):
        raise web.HTTPBadRequest(text="session_note must be text")
    try:
        path = _recording(request).start(device_id, interval, note[:2048])
    except RuntimeError as exc:
        if str(exc) == "recording commands disabled":
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response({"state": "RECORDING", "session_dir": str(path)})


async def stop_recording(request):
    body = await _body(request)
    device_id = _require_device_id(request, body)
    try:
        _recording(request).stop(device_id)
    except KeyError as exc:
        raise web.HTTPNotFound(text="recording not active") from exc
    except RuntimeError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc
    return web.json_response({"state": "STOPPED"})


async def change_recording_interval(request):
    body = await _body(request)
    interval = _positive_interval(body)
    device_id = _require_device_id(request, body)
    _validate_recording_interval_for_device(request, device_id, interval)
    try:
        _recording(request).set_interval(device_id, interval)
    except KeyError as exc:
        raise web.HTTPNotFound(text="recording not active") from exc
    except RuntimeError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc
    return web.json_response({"state": "RECORDING", "interval_s": interval})


async def get_scope_status(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _scope_service(request)
    return _scope_status_json(service, service.status(device_id))


async def start_scope(request):
    device_id = request.match_info["device_id"]
    device = _device_config(request, device_id)
    service = _scope_service(request)
    body = await _body(request)
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not username:
        body.clear()
        raise web.HTTPBadRequest(text="username is required")
    if not isinstance(password, str) or not password:
        username = ""
        body.clear()
        raise web.HTTPBadRequest(text="password is required")
    try:
        status = await service.start(device_id, device.host, username, password)
    except ScopeSessionConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    except ScopeServiceError as exc:
        raise web.HTTPBadGateway(text=f"scope session start failed: {exc}") from exc
    finally:
        username = ""
        password = ""
        body.clear()
    return _scope_status_json(service, status)


async def hold_scope(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _scope_service(request)
    try:
        status = service.hold(device_id)
    except ScopeServiceError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return _scope_status_json(service, status)


async def live_scope(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _scope_service(request)
    try:
        status = service.live(device_id)
    except ScopeServiceError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return _scope_status_json(service, status)


async def stop_scope(request):
    device_id = request.match_info["device_id"]
    _device_config(request, device_id)
    service = _scope_service(request)
    status = await service.stop(device_id)
    return _scope_status_json(service, status)
