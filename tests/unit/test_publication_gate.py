from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "publication_gate.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("ari_publication_gate", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publication_gate_accepts_clean_public_files_and_rejects_secret_or_debris(tmp_path: Path) -> None:
    module = _load_tool()
    clean = tmp_path / "clean.txt"
    clean.write_text("public scientific documentation\n", encoding="utf-8")
    assert module.scan_files(tmp_path, [Path("clean.txt")]) == []

    private_key = tmp_path / "key.txt"
    private_key.write_text("-----BEGIN " + "PRIVATE KEY-----\n", encoding="utf-8")
    findings = module.scan_files(tmp_path, [Path("key.txt")])
    assert any("private key" in finding.lower() for finding in findings)

    cache = tmp_path / "__pycache__" / "module.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    findings = module.scan_files(tmp_path, [Path("__pycache__/module.pyc")])
    assert any("forbidden path" in finding.lower() for finding in findings)


def test_publication_gate_rejects_private_deployment_identity_but_allows_negative_regression_assertion(tmp_path: Path) -> None:
    module = _load_tool()
    leaked = tmp_path / "leaked.txt"
    leaked.write_text("host = " + "192." + "168.1.181\nname = emonio-" + "da5fb4\n", encoding="utf-8")
    findings = module.scan_files(tmp_path, [Path("leaked.txt")])
    assert any("private ipv4" in finding.lower() for finding in findings)
    assert any("field device identity" in finding.lower() for finding in findings)

    regression = tmp_path / "regression.py"
    private_prefix = "192." + "168."
    field_name = "emonio-" + "da5fb4"
    regression.write_text(
        f'assert "{private_prefix}" not in source\nassert "{field_name}" not in html\n',
        encoding="utf-8",
    )
    assert module.scan_files(tmp_path, [Path("regression.py")]) == []


def test_publication_gate_source_and_its_regression_tests_are_self_clean() -> None:
    module = _load_tool()
    paths = [Path("tools/publication_gate.py"), Path("tests/unit/test_publication_gate.py")]
    assert module.scan_files(ROOT, paths) == []
