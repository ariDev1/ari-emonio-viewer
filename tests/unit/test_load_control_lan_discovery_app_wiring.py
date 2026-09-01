from inspect import signature

from emonio_viewer.server.app_v0416 import create_app


def test_app_v0416_accepts_explicit_lan_discovery_and_qualification_services() -> None:
    parameters = signature(create_app).parameters
    assert "lan_discovery_service" in parameters
    assert "qualification_service" in parameters


def test_app_v0416_stores_lan_discovery_and_qualification_services_under_dedicated_keys() -> None:
    source = __import__("inspect").getsource(create_app)
    assert "LAN_ACTUATOR_DISCOVERY_SERVICE_KEY" in source
    assert "LanActuatorDiscoveryService" in source
    assert "LOAD_CONTROL_QUALIFICATION_SERVICE_KEY" in source
    assert "LoadControlQualificationService" in source
    assert "LOAD_CONTROL_SERVICE_KEY" in source


def test_app_v0416_wires_one_shared_qualified_channel_into_stage2_and_stage3a() -> None:
    parameters = signature(create_app).parameters
    assert "qualified_channel" in parameters
    assert "stage3a_service" in parameters

    source = __import__("inspect").getsource(create_app)
    assert "QualifiedActuatorChannel" in source
    assert "qualified_channel=qualified_channel" in source
    assert "Stage3ASafeCommandService" in source
    assert "LOAD_CONTROL_STAGE3A_SERVICE_KEY" in source
    assert "diagnostic_log=qualification_service.diagnostic_log" in source


def test_app_v0416_owns_stage3a_startup_and_cleanup() -> None:
    source = __import__("inspect").getsource(create_app)
    assert "await stage3a_service.start()" in source
    assert "await stage3a_service.close()" in source
    assert "app.on_startup.append(start_stage3a)" in source
    assert "app.on_cleanup.append(stop_stage3a)" in source
