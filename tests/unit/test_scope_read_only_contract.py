from __future__ import annotations

import ast
from pathlib import Path


def test_scope_transport_has_only_login_post_and_fixed_scope_websocket_payload() -> None:
    client = Path("src/emonio_viewer/scope/client.py").read_text(encoding="utf-8")
    protocol = Path("src/emonio_viewer/scope/protocol.py").read_text(encoding="utf-8")
    assert client.count("session.post(") == 1
    assert 'f"{base}/login"' in client
    assert client.count("send_str(SCOPE_COMMAND)") == 1
    assert "send_bytes(" not in client
    assert 'SCOPE_COMMAND = "scope"' in protocol


def test_scope_package_is_isolated_from_modbus_measurement_recording_and_ct_evidence() -> None:
    forbidden_prefixes = (
        "emonio_viewer.modbus",
        "emonio_viewer.measurement",
        "emonio_viewer.recording",
        "emonio_viewer.device_evidence",
    )
    for path in Path("src/emonio_viewer/scope").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(not name.startswith(forbidden_prefixes) for name in names), (path, names)


def test_credentials_are_not_part_of_scope_models_or_persistence_sources() -> None:
    model = Path("src/emonio_viewer/scope/model.py").read_text(encoding="utf-8").lower()
    assert "username" not in model
    assert "password" not in model
    for root in (
        Path("src/emonio_viewer/recording"),
        Path("src/emonio_viewer/config"),
    ):
        source = "\n".join(path.read_text(encoding="utf-8").lower() for path in root.glob("*.py"))
        assert "scope password" not in source
        assert "scope username" not in source
