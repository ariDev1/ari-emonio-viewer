from pathlib import Path

from aiohttp import web

from emonio_viewer import __version__
from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.load_control.automatic_observation import PControlObserverService
from emonio_viewer.load_control.characterization_service import Stage4BCharacterizationService
from emonio_viewer.load_control.lan_discovery import LanActuatorDiscoveryService
from emonio_viewer.load_control.manual_pwm import Stage3BManualPwmCommandService
from emonio_viewer.load_control.qualification import LoadControlQualificationService
from emonio_viewer.load_control.qualified_channel import QualifiedActuatorChannel
from emonio_viewer.load_control.service import LoadControlService
from emonio_viewer.load_control.stage3a import Stage3ASafeCommandService
from emonio_viewer.load_control.zero_export_service import Stage4CZeroExportControllerService
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore

from .api_v0416 import register_api_routes
from .keys import (
    CHARACTERIZATION_SERVICE_KEY,
    CT_CONFIGURATION_SERVICE_KEY,
    DEVICE_CONNECTOR_KEY,
    DEVICE_LIFECYCLE_SERVICE_KEY,
    EVENT_BUS_KEY,
    LAN_ACTUATOR_DISCOVERY_SERVICE_KEY,
    LOAD_CONTROL_QUALIFICATION_SERVICE_KEY,
    LOAD_CONTROL_SERVICE_KEY,
    LOAD_CONTROL_STAGE3A_SERVICE_KEY,
    MODBUS_DEVICE_EVIDENCE_SERVICE_KEY,
    P_CONTROL_OBSERVER_SERVICE_KEY,
    RECORDING_MANAGER_KEY,
    RUNTIME_CONFIG_KEY,
    RUNTIME_STORE_KEY,
    SCOPE_SERVICE_KEY,
    ZERO_EXPORT_CONTROLLER_SERVICE_KEY,
)
from .load_control_api import register_load_control_routes
from .load_control_stage3b_api import register_load_control_stage3b_routes
from .load_control_stage4a_api import register_load_control_stage4a_routes
from .load_control_stage4b_characterization_api import (
    register_load_control_stage4b_characterization_routes,
)
from .load_control_stage4c_api import register_load_control_stage4c_routes
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
    lan_discovery_service: LanActuatorDiscoveryService | None = None,
    qualification_service: LoadControlQualificationService | None = None,
    qualified_channel: QualifiedActuatorChannel | None = None,
    stage3a_service: Stage3ASafeCommandService | None = None,
    p_control_observer_service: PControlObserverService | None = None,
    characterization_service: Stage4BCharacterizationService | None = None,
    zero_export_controller_service: Stage4CZeroExportControllerService | None = None,
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

    if lan_discovery_service is None:
        lan_discovery_service = LanActuatorDiscoveryService()
    app[LAN_ACTUATOR_DISCOVERY_SERVICE_KEY] = lan_discovery_service

    if qualified_channel is None:
        qualified_channel = QualifiedActuatorChannel()

    if qualification_service is None:
        qualification_service = LoadControlQualificationService(
            lan_discovery_service,
            qualified_channel=qualified_channel,
        )
    app[LOAD_CONTROL_QUALIFICATION_SERVICE_KEY] = qualification_service

    if stage3a_service is None:
        stage3a_service = Stage3BManualPwmCommandService(
            bus,
            config,
            qualified_channel,
            diagnostic_log=qualification_service.diagnostic_log,
        )
    app[LOAD_CONTROL_STAGE3A_SERVICE_KEY] = stage3a_service

    if p_control_observer_service is None:
        def qualification_status_provider():
            return qualification_service.status()

        def manual_pwm_status_provider():
            getter = getattr(stage3a_service, "manual_pwm_status", None)
            if not callable(getter):
                return None
            return getter()

        p_control_observer_service = PControlObserverService(
            bus,
            config,
            qualification_status=qualification_status_provider,
            manual_pwm_status=manual_pwm_status_provider,
        )
    app[P_CONTROL_OBSERVER_SERVICE_KEY] = p_control_observer_service

    if characterization_service is None:
        characterization_service = Stage4BCharacterizationService(
            bus,
            config,
            manual_pwm=stage3a_service,
        )
    app[CHARACTERIZATION_SERVICE_KEY] = characterization_service

    if zero_export_controller_service is None:
        zero_export_controller_service = Stage4CZeroExportControllerService(
            bus,
            config,
            manual_pwm=stage3a_service,
        )
    app[ZERO_EXPORT_CONTROLLER_SERVICE_KEY] = zero_export_controller_service

    async def start_load_control(_app: web.Application) -> None:
        await load_control_service.start()

    async def start_stage3a(_app: web.Application) -> None:
        await stage3a_service.start()

    async def start_p_control_observer(_app: web.Application) -> None:
        await p_control_observer_service.start()

    async def start_characterization(_app: web.Application) -> None:
        await characterization_service.start()

    async def start_zero_export_controller(_app: web.Application) -> None:
        await zero_export_controller_service.start()

    async def stop_zero_export_controller(_app: web.Application) -> None:
        await zero_export_controller_service.close()

    async def stop_characterization(_app: web.Application) -> None:
        await characterization_service.close()

    async def stop_p_control_observer(_app: web.Application) -> None:
        await p_control_observer_service.close()

    async def stop_stage3a(_app: web.Application) -> None:
        await stage3a_service.close()

    async def stop_load_control(_app: web.Application) -> None:
        await load_control_service.close()

    async def stop_load_control_qualification(_app: web.Application) -> None:
        await qualification_service.close()

    app.on_startup.append(start_load_control)
    app.on_startup.append(start_stage3a)
    app.on_startup.append(start_p_control_observer)
    app.on_startup.append(start_characterization)
    app.on_startup.append(start_zero_export_controller)
    app.on_cleanup.append(stop_zero_export_controller)
    app.on_cleanup.append(stop_characterization)
    app.on_cleanup.append(stop_p_control_observer)
    app.on_cleanup.append(stop_stage3a)
    app.on_cleanup.append(stop_load_control_qualification)
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
        load_control_css = f'<link rel="stylesheet" href="{static_prefix}css/load-control/load-control.css">'
        p_control_observer_css = f'<link rel="stylesheet" href="{static_prefix}css/load-control/p-control-observer.css">'
        p_characterization_css = f'<link rel="stylesheet" href="{static_prefix}css/load-control/p-characterization.css">'
        monitor_script = f'<script type="module" src="{static_prefix}js/recording-monitor-ui.js"></script>'
        load_control_script = f'<script type="module" src="{static_prefix}js/load-control-ui.js"></script>'
        load_control_stage3b_script = f'<script type="module" src="{static_prefix}js/load-control-stage3b-ui.js"></script>'
        load_control_stage4a_script = f'<script type="module" src="{static_prefix}js/load-control-stage4a-ui.js"></script>'
        load_control_stage4b_characterization_script = f'<script type="module" src="{static_prefix}js/load-control-stage4b-characterization-ui.js"></script>'
        source = source.replace(
            "</head>",
            f"  {monitor_css}\n  {load_control_css}\n  {p_control_observer_css}\n  {p_characterization_css}\n</head>",
            1,
        )
        source = source.replace(
            "</body>",
            f"  {monitor_script}\n  {load_control_script}\n  {load_control_stage3b_script}\n  {load_control_stage4a_script}\n  {load_control_stage4b_characterization_script}\n</body>",
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
    register_load_control_stage3b_routes(app)
    register_load_control_stage4a_routes(app)
    register_load_control_stage4b_characterization_routes(app)
    register_load_control_stage4c_routes(app)
    return app
