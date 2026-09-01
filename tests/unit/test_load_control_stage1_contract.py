from pathlib import Path


def test_stage1_load_control_contains_no_real_actuator_network_implementation() -> None:
    root = Path("src/emonio_viewer/load_control")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*.py"))
    )

    forbidden = (
        "WebSocketActuatorSession",
        "MdnsActuatorDiscovery",
        "zeroconf",
        "socket.socket",
        "aiohttp.ClientSession",
        "websockets.connect",
        "serial.Serial",
        "machine.PWM",
    )
    for token in forbidden:
        assert token not in source


def test_stage1_service_identifies_mock_only_boundary() -> None:
    service = Path("src/emonio_viewer/load_control/service.py").read_text(encoding="utf-8")
    assert '"stage": "STAGE_1_MOCK_ONLY"' in service
    assert '"mock_only": True' in service
    assert "MockActuatorDiscovery" in service
    assert "MockActuatorSession" in service
