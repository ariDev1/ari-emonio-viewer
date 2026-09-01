from inspect import signature

from emonio_viewer.server.app_v0416 import create_app


def test_app_v0416_accepts_explicit_lan_discovery_service() -> None:
    parameters = signature(create_app).parameters
    assert "lan_discovery_service" in parameters


def test_app_v0416_stores_lan_discovery_service_under_dedicated_key() -> None:
    source = __import__("inspect").getsource(create_app)
    assert "LAN_ACTUATOR_DISCOVERY_SERVICE_KEY" in source
    assert "LanActuatorDiscoveryService" in source
