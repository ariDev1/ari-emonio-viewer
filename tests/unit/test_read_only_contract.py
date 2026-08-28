from pathlib import Path


def test_production_modbus_source_has_no_write_api() -> None:
    root = Path("src/emonio_viewer/modbus")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "write_register",
        "write_registers",
        "write_coil",
        "write_coils",
        "0x05",
        "0x06",
        "0x0F",
        "0x10",
    )
    assert all(token not in source for token in forbidden)


def test_production_ct_telnet_source_has_only_fixed_conf_reads() -> None:
    import ast

    source_path = Path("src/emonio_viewer/device_evidence/telnet.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    conf_strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("conf ")
    }
    assert conf_strings == {
        "conf ct_type",
        "conf ct_voltage",
        "conf ct_range",
        "conf ct_invert",
        "conf ct_didt",
    }
    for command in conf_strings:
        assert "=" not in command
        assert command.startswith("conf ct_")


def test_recording_source_has_no_ct_credentials_or_configuration_evidence() -> None:
    root = Path("src/emonio_viewer/recording")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for token in ("password", "ct_type", "ct_voltage", "ct_range", "ct_invert", "ct_didt"):
        assert token not in source
