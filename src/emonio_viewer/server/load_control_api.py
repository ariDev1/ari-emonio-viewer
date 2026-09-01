from __future__ import annotations

from aiohttp import web

from emonio_viewer.load_control.qualification import (
    LoadControlQualificationError,
    QualificationStatus,
)
from emonio_viewer.load_control.service import LoadControlCommandError
from emonio_viewer.load_control.stage3a import Stage3AError, Stage3AStatus

from .keys import (
    LAN_ACTUATOR_DISCOVERY_SERVICE_KEY,
    LOAD_CONTROL_QUALIFICATION_SERVICE_KEY,
    LOAD_CONTROL_SERVICE_KEY,
    LOAD_CONTROL_STAGE3A_SERVICE_KEY,
)


def register_load_control_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/load-control/status", get_load_control_status)
    app.router.add_get("/api/v1/load-control/discovered-actuators", get_discovered_actuators)
    app.router.add_post("/api/v1/load-control/lan-discovery/scan", scan_lan_actuators)
    app.router.add_post("/api/v1/load-control/lan-qualification/connect", connect_lan_actuator)
    app.router.add_get("/api/v1/load-control/lan-qualification/status", get_lan_qualification_status)
    app.router.add_post("/api/v1/load-control/lan-qualification/disconnect", disconnect_lan_actuator)
    app.router.add_get("/api/v1/load-control/lan-diagnostics/log", get_lan_diagnostic_log)
    app.router.add_get("/api/v1/load-control/safe-test/sources", get_safe_test_sources)
    app.router.add_get("/api/v1/load-control/safe-test/status", get_safe_test_status)
    app.router.add_post("/api/v1/load-control/safe-test/source", select_safe_test_source)
    app.router.add_post("/api/v1/load-control/safe-test/run", run_safe_test)
    app.router.add_get("/api/v1/load-control/evidence/recent", get_recent_evidence)
    app.router.add_post("/api/v1/load-control/binding", configure_binding)
    app.router.add_post("/api/v1/load-control/config", configure_limits)
    app.router.add_post("/api/v1/load-control/timing", configure_timing)
    app.router.add_post("/api/v1/load-control/enable", enable_load_control)
    app.router.add_post("/api/v1/load-control/disable", disable_load_control)


def _service(request: web.Request):
    service = request.app.get(LOAD_CONTROL_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="load-control service is unavailable")
    return service


def _lan_discovery_service(request: web.Request):
    service = request.app.get(LAN_ACTUATOR_DISCOVERY_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="LAN actuator discovery service is unavailable")
    return service


def _qualification_service(request: web.Request):
    service = request.app.get(LOAD_CONTROL_QUALIFICATION_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="load-control qualification service is unavailable")
    return service


def _stage3a_service(request: web.Request):
    service = request.app.get(LOAD_CONTROL_STAGE3A_SERVICE_KEY)
    if service is None:
        raise web.HTTPServiceUnavailable(text="Stage-3A SAFE test service is unavailable")
    return service


def _optional_diagnostic_log(request: web.Request):
    service = request.app.get(LOAD_CONTROL_QUALIFICATION_SERVICE_KEY)
    if service is None:
        return None
    return getattr(service, "diagnostic_log", None)


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="request body must be a JSON object")
    return body


def _required_text(body: dict, name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value:
        raise web.HTTPBadRequest(text=f"{name} is required")
    return value


def _required_number(body: dict, name: str) -> float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise web.HTTPBadRequest(text=f"{name} must be numeric")
    return float(value)


def _query_integer(
    request: web.Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    raw = request.query.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise web.HTTPBadRequest(text=f"{name} must be >= {minimum}")
        raise web.HTTPBadRequest(text=f"{name} must be between {minimum} and {maximum}")
    return value


def _command_error(exc: LoadControlCommandError) -> web.HTTPConflict:
    return web.HTTPConflict(
        text=str(exc),
        content_type="text/plain",
    )


def _descriptor_json(item) -> dict:
    return {
        "node_id": item.node_id,
        "location": item.location,
        "device_class": item.device_class,
        "capabilities": list(item.capabilities),
        "p_max": {"a": item.p_max.a, "b": item.p_max.b, "c": item.p_max.c},
    }


def _qualification_json(status: QualificationStatus) -> dict:
    p_max = status.p_max
    return {
        "state": status.state.value,
        "connected": status.connected,
        "hello_qualified": status.hello_qualified,
        "selected_node_id": status.selected_node_id,
        "node_id": status.node_id,
        "boot_id": status.boot_id,
        "protocol_version": status.protocol_version,
        "device_class": status.device_class,
        "capabilities": list(status.capabilities),
        "p_max": (
            None
            if p_max is None
            else {"a": p_max.a, "b": p_max.b, "c": p_max.c}
        ),
        "location": status.location,
        "last_error": status.last_error,
    }


def _stage3a_status_json(status: Stage3AStatus) -> dict:
    return {
        "state": status.state.value,
        "selected_source_id": status.selected_source_id,
        "sample_cycle_id": status.sample_cycle_id,
        "command_sequence": status.command_sequence,
        "ack_result": status.ack_result,
        "rejection_reason": status.rejection_reason,
        "admissible": status.admissible,
    }


def _stage3a_source_json(item) -> dict:
    return {
        "device_id": item.id,
        "name": item.name,
        "poll_interval_s": item.poll_interval_s,
    }


def _diagnostic_event_json(item) -> dict:
    return {
        "sequence": item.sequence,
        "utc": item.utc,
        "event": item.event,
        "line": item.line,
    }


async def get_load_control_status(request: web.Request) -> web.Response:
    return web.json_response(_service(request).status())


async def get_discovered_actuators(request: web.Request) -> web.Response:
    service = _service(request)
    visible = await service.refresh_discovery()
    return web.json_response([_descriptor_json(item) for item in visible])


async def scan_lan_actuators(request: web.Request) -> web.Response:
    body = await _body(request)
    discovery_window_s = _required_number(body, "discovery_window_s")
    resolve_timeout_s = _required_number(body, "resolve_timeout_s")
    diagnostic_log = _optional_diagnostic_log(request)
    if diagnostic_log is not None:
        diagnostic_log.append(
            "LAN_SCAN_STARTED",
            discovery_window_s=discovery_window_s,
            resolve_timeout_s=resolve_timeout_s,
        )
    try:
        visible = await _lan_discovery_service(request).scan(
            discovery_window_s=discovery_window_s,
            resolve_timeout_s=resolve_timeout_s,
        )
    except ValueError as exc:
        if diagnostic_log is not None:
            diagnostic_log.append("LAN_SCAN_FAILED", reason=str(exc))
        raise web.HTTPBadRequest(text=str(exc)) from exc

    if diagnostic_log is not None:
        for item in visible:
            diagnostic_log.append(
                "ACTUATOR_DISCOVERED",
                node_id=item.node_id,
                location=item.location,
                device_class=item.device_class,
                capabilities=",".join(item.capabilities),
                p_max_a_w=item.p_max.a,
                p_max_b_w=item.p_max.b,
                p_max_c_w=item.p_max.c,
            )
        diagnostic_log.append("LAN_SCAN_COMPLETE", count=len(visible))
    return web.json_response([_descriptor_json(item) for item in visible])


async def connect_lan_actuator(request: web.Request) -> web.Response:
    body = await _body(request)
    node_id = _required_text(body, "node_id")
    try:
        status = await _qualification_service(request).connect(node_id)
    except LoadControlQualificationError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_qualification_json(status))


async def get_lan_qualification_status(request: web.Request) -> web.Response:
    return web.json_response(_qualification_json(_qualification_service(request).status()))


async def disconnect_lan_actuator(request: web.Request) -> web.Response:
    status = await _qualification_service(request).disconnect()
    return web.json_response(_qualification_json(status))


async def get_lan_diagnostic_log(request: web.Request) -> web.Response:
    after_sequence = _query_integer(
        request,
        "after",
        default=0,
        minimum=0,
    )
    limit = _query_integer(
        request,
        "limit",
        default=200,
        minimum=1,
        maximum=200,
    )
    diagnostic_log = _qualification_service(request).diagnostic_log
    events = diagnostic_log.recent(
        after_sequence=after_sequence,
        limit=limit,
    )
    return web.json_response(
        {
            "latest_sequence": diagnostic_log.latest_sequence,
            "events": [_diagnostic_event_json(item) for item in events],
        }
    )


async def get_safe_test_sources(request: web.Request) -> web.Response:
    return web.json_response(
        [_stage3a_source_json(item) for item in _stage3a_service(request).sources()]
    )


async def get_safe_test_status(request: web.Request) -> web.Response:
    return web.json_response(_stage3a_status_json(_stage3a_service(request).status()))


async def select_safe_test_source(request: web.Request) -> web.Response:
    body = await _body(request)
    device_id = _required_text(body, "emonio_device_id")
    try:
        status = await _stage3a_service(request).select_source(device_id)
    except Stage3AError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_stage3a_status_json(status))


async def run_safe_test(request: web.Request) -> web.Response:
    try:
        status = await _stage3a_service(request).run_safe_test()
    except Stage3AError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_stage3a_status_json(status))


async def get_recent_evidence(request: web.Request) -> web.Response:
    raw_limit = request.query.get("limit", "100")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="limit must be an integer") from exc
    try:
        payload = _service(request).recent_evidence(limit)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response(list(payload))


async def configure_binding(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        await _service(request).configure_binding(
            emonio_device_id=_required_text(body, "emonio_device_id"),
            actuator_node_id=_required_text(body, "actuator_node_id"),
        )
    except LoadControlCommandError as exc:
        raise _command_error(exc) from exc
    return web.json_response(_service(request).status())


async def configure_limits(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        await _service(request).configure_limits(
            p_reserve=_required_number(body, "p_reserve"),
            operator_limit_a=_required_number(body, "operator_limit_a"),
            operator_limit_b=_required_number(body, "operator_limit_b"),
            operator_limit_c=_required_number(body, "operator_limit_c"),
        )
    except LoadControlCommandError as exc:
        raise _command_error(exc) from exc
    return web.json_response(_service(request).status())


async def configure_timing(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        await _service(request).configure_timing(
            control_sample_max_age_s=_required_number(body, "control_sample_max_age_s"),
            ack_timeout_s=_required_number(body, "ack_timeout_s"),
        )
    except LoadControlCommandError as exc:
        raise _command_error(exc) from exc
    return web.json_response(_service(request).status())


async def enable_load_control(request: web.Request) -> web.Response:
    try:
        await _service(request).enable()
    except LoadControlCommandError as exc:
        raise _command_error(exc) from exc
    return web.json_response(_service(request).status())


async def disable_load_control(request: web.Request) -> web.Response:
    try:
        await _service(request).disable()
    except LoadControlCommandError as exc:
        raise _command_error(exc) from exc
    return web.json_response(_service(request).status())
