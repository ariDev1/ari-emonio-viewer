from aiohttp import web

from emonio_viewer.config.model import RuntimeConfig
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.device_evidence.service import CtConfigurationService
from emonio_viewer.scope.service import ScopeService


RUNTIME_CONFIG_KEY = web.AppKey("runtime_config", RuntimeConfig)
RUNTIME_STORE_KEY = web.AppKey("runtime_store", RuntimeStore)
EVENT_BUS_KEY = web.AppKey("event_bus", RuntimeEventBus)
RECORDING_MANAGER_KEY = web.AppKey("recording_manager", object)
DEVICE_CONNECTOR_KEY = web.AppKey("device_connector", object)

CT_CONFIGURATION_SERVICE_KEY = web.AppKey("ct_configuration_service", CtConfigurationService)
SCOPE_SERVICE_KEY = web.AppKey("scope_service", ScopeService)
