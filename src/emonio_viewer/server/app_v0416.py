from pathlib import Path

from aiohttp import web

from emonio_viewer import __version__
from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.load_control.service import LoadControlService
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore

from .api_v0416 import register_api_routes
from .keys import (
    CT_CONFIGURATION_SERVICE_KEY,
    DEVICE_CONNECTOR_KEY,
    DEVICE_LIFECYCLE_SERVICE_KEY,
    EVENT_BUS_KEY,
    LOAD_CONTROL_SERVICE_KEY,
    MODBUS_DEVICE_EVIDENCE_SERVICE_KEY,
    RECORDING_MANAGER_KEY,
    RUNTIME_CONFIG_KEY,
    RUNTIME_STORE_KEY,
    SCOPE_SERVICE_KEY,
)
from .load_control_api import register_load_control_routes
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
    lifecycle_service=None,
    load_control_service: LoadControlService | None = None,
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
    if lifecycle_service is not None:
        app[DEVICE_LIFECYCLE_SERVICE_KEY] = lifecycle_service

    if load_control_service is None:
        project_root = frontend_dir.parent
        load_control_service = LoadControlService(
            bus,
            config_path=project_root / "config" / "load-control-stage1.json",
            evidence_path=project_root / "recordings" / "load-control-evidence.jsonl",
        )
    app[LOAD_CONTROL_SERVICE_KEY] = load_control_service

    async def start_load_control(_app: web.Application) -> None:
        await load_control_service.start()

    async def stop_load_control(_app: web.Application) -> None:
        await load_control_service.close()

    app.on_startup.append(start_load_control)
    app.on_cleanup.append(stop_load_control)

    static_prefix = f"/static/{__version__}/"

    async def index(_request: web.Request) -> web.Response:
        source = (frontend_dir / "index.html").read_text(encoding="utf-8")
        source = source.replace(
            '<span class="eyebrow">ARI EMONIO VIEWER</span>',
            f'<span class="eyebrow">ARI EMONIO VIEWER · v{__version__}</span>',
            1,
        )
        source = source.replace('"/static/', f'"{static_prefix}')
        monitor_css = f'<link rel="stylesheet" href="{static_prefix}css/recording-monitor.css">'
        load_control_css = f'<link rel="stylesheet" href="{static_prefix}css/load-control.css">'
        monitor_script = f'<script type="module" src="{static_prefix}js/recording-monitor-ui.js"></script>'
        load_control_script = f'<script type="module" src="{static_prefix}js/load-control-ui.js"></script>'
        source = source.replace(
            "</head>",
            f"  {monitor_css}\n  {load_control_css}\n</head>",
            1,
        )
        source = source.replace(
            "</body>",
            f"  {monitor_script}\n  {load_control_script}\n</body>",
            1,
        )
        return web.Response(
            text=source,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    app.router.add_get("/", index)
    app.router.add_static(static_prefix, frontend_dir, show_index=False)
    app.router.add_get("/ws/v1/measurements", websocket_measurements)
    register_api_routes(app)
    register_load_control_routes(app)
    return app
