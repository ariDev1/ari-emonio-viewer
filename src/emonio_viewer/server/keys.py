from aiohttp import web

from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.device_evidence.service import CtConfigurationService, ModbusDeviceEvidenceService
from emonio_viewer.lifecycle.service import DeviceLifecycleService
from emonio_viewer.load_control.lan_discovery import LanActuatorDiscoveryService
from emonio_viewer.load_control.qualification import LoadControlQualificationService
from emonio_viewer.load_control.service import LoadControlService
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.scope.service import ScopeService


RUNTIME_CONFIG_KEY = web.AppKey("runtime_config", RuntimeConfig)
RUNTIME_STORE_KEY = web.AppKey("runtime_store", RuntimeStore)
EVENT_BUS_KEY = web.AppKey("event_bus", RuntimeEventBus)
RECORDING_MANAGER_KEY = web.AppKey("recording_manager", object)
DEVICE_CONNECTOR_KEY = web.AppKey("device_connector", object)
DEVICE_LIFECYCLE_SERVICE_KEY = web.AppKey("device_lifecycle_service", DeviceLifecycleService)

CT_CONFIGURATION_SERVICE_KEY = web.AppKey("ct_configuration_service", CtConfigurationService)
MODBUS_DEVICE_EVIDENCE_SERVICE_KEY = web.AppKey("modbus_device_evidence_service", ModbusDeviceEvidenceService)
SCOPE_SERVICE_KEY = web.AppKey("scope_service", ScopeService)
LOAD_CONTROL_SERVICE_KEY = web.AppKey("load_control_service", LoadControlService)
LAN_ACTUATOR_DISCOVERY_SERVICE_KEY = web.AppKey("lan_actuator_discovery_service", LanActuatorDiscoveryService)
LOAD_CONTROL_QUALIFICATION_SERVICE_KEY = web.AppKey(
    "load_control_qualification_service",
    LoadControlQualificationService,
)
