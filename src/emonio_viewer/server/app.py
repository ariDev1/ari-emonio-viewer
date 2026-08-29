from pathlib import Path

from aiohttp import web

from emonio_viewer import __version__
from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore

from .api import register_api_routes
from .keys import (
    CT_CONFIGURATION_SERVICE_KEY,
    MODBUS_DEVICE_EVIDENCE_SERVICE_KEY,
    DEVICE_CONNECTOR_KEY,
    EVENT_BUS_KEY,
    RECORDING_MANAGER_KEY,
    RUNTIME_CONFIG_KEY,
    RUNTIME_STORE_KEY,
    SCOPE_SERVICE_KEY,
)
from .websocket import websocket_measurements


def create_app(
    config: RuntimeConfig,
    store: RuntimeStore,
    bus: RuntimeEventBus,
    recording: RecordingManager,
    frontend_dir: Path,
    *,
    connector=None,
    ct_configuration=None,
    modbus_evidence=None,
    scope_service=None,
) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    app[RUNTIME_CONFIG_KEY] = config
    app[RUNTIME_STORE_KEY] = store
    app[EVENT_BUS_KEY] = bus
    app[RECORDING_MANAGER_KEY] = recording
    if connector is not None:
        app[DEVICE_CONNECTOR_KEY] = connector
    if ct_configuration is not None:
        app[CT_CONFIGURATION_SERVICE_KEY] = ct_configuration
    if modbus_evidence is not None:
        app[MODBUS_DEVICE_EVIDENCE_SERVICE_KEY] = modbus_evidence
    if scope_service is not None:
        app[SCOPE_SERVICE_KEY] = scope_service

    static_prefix = f"/static/{__version__}/"

    async def index(_request: web.Request) -> web.Response:
        source = (frontend_dir / "index.html").read_text(encoding="utf-8")
        source = source.replace(
            '<span class="eyebrow">ARI EMONIO VIEWER</span>',
            f'<span class="eyebrow">ARI EMONIO VIEWER · v{__version__}</span>',
            1,
        )
        source = source.replace('"/static/', f'"{static_prefix}')
        return web.Response(
            text=source,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    app.router.add_get("/", index)
    app.router.add_static(static_prefix, frontend_dir, show_index=False)
    app.router.add_get("/ws/v1/measurements", websocket_measurements)
    register_api_routes(app)
    return app
