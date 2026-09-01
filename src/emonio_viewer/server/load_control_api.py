from __future__ import annotations

from aiohttp import web

from emonio_viewer.load_control.service import LoadControlCommandError

from .keys import LAN_ACTUATOR_DISCOVERY_SERVICE_KEY, LOAD_CONTROL_SERVICE_KEY


def register_load_control_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/load-control/status", get_load_control_status)
    app.router.add_get("/api/v1/load-control/discovered-actuators", get_discovered_actuators)
    app.router.add_post("/api/v1/load-control/lan-discovery/scan", scan_lan_actuators)
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


async def get_load_control_status(request: web.Request) -> web.Response:
    return web.json_response(_service(request).status())


async def get_discovered_actuators(request: web.Request) -> web.Response:
    service = _service(request)
    visible = await service.refresh_discovery()
    return web.json_response([_descriptor_json(item) for item in visible])


async def scan_lan_actuators(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        visible = await _lan_discovery_service(request).scan(
            discovery_window_s=_required_number(body, "discovery_window_s"),
            resolve_timeout_s=_required_number(body, "resolve_timeout_s"),
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response([_descriptor_json(item) for item in visible])


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
