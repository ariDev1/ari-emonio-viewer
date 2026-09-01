from pathlib import Path


def test_viewer_load_control_contains_no_physical_output_implementation() -> None:
    root = Path("src/emonio_viewer/load_control")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*.py"))
    )

    forbidden = (
        "websockets.connect",
        "serial.Serial",
        "machine.PWM",
    )
    for token in forbidden:
        assert token not in source


def test_active_service_remains_mock_only_until_transport_is_explicitly_promoted() -> None:
    service = Path("src/emonio_viewer/load_control/service.py").read_text(encoding="utf-8")
    assert '"stage": "STAGE_1_MOCK_ONLY"' in service
    assert '"mock_only": True' in service
    assert "MockActuatorDiscovery" in service
    assert "MockActuatorSession" in service
    assert "MdnsActuatorDiscovery" not in service
    assert "ZeroconfMdnsBackend" not in service
    assert "WebSocketActuatorSession" not in service
