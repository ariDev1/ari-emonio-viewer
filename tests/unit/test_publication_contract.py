from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_public_default_configuration_contains_only_disabled_example_device() -> None:
    raw = tomllib.loads((ROOT / "config" / "emonio-viewer.toml").read_text(encoding="utf-8"))
    assert raw["viewer"]["default_device"] == "emonio-example"
    assert len(raw["devices"]) == 1
    device = raw["devices"][0]
    assert device["id"] == "emonio-example"
    assert device["name"] == "emonio-example"
    assert device["host"] == "192.0.2.10"
    assert device["enabled"] is False
    assert device["port"] == 502
    assert device["unit_id"] == 1
    assert device["poll_interval_s"] == 2.0
    assert device["timeout_s"] == 2.0
    assert device["firmware_version"] == "3.0.79-release"


def test_public_frontend_target_placeholder_contains_no_private_field_identity() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'placeholder="192.0.2.10 or emonio-example"' in html
    assert "192.0.2.11" not in html
    assert "emonio-da5fb4" not in html


def test_public_tree_excludes_internal_superpowers_planning_documents() -> None:
    assert not (ROOT / "docs" / "superpowers").exists()


def test_publication_documentation_exists_and_states_security_and_license_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "source-available" in readme.lower()
    assert "SECURITY.md" in readme
    assert "CONTRIBUTING.md" in readme
    assert "natural person" in license_text.lower()
    assert "commercial license" in license_text.lower()
    assert "modbus writes are forbidden" in security.lower()
    assert "runtime-only" in security.lower()
    assert "complete acceptance suite" in contributing.lower()


def test_gitignore_covers_local_and_generated_publication_debris_without_broad_science_patterns() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = (
        ".coverage",
        "htmlcov/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".idea/",
        ".vscode/",
        "*.swp",
        "*~",
        ".DS_Store",
        ".env",
        "*.log",
        "*.sqlite",
        "config/emonio-viewer.local.toml",
    )
    for item in required:
        assert item in text
    for forbidden in ("*.csv", "*.json", "*.bin"):
        assert forbidden not in text


def test_pyproject_uses_security_qualified_aiohttp_target_and_direct_yarl_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert "aiohttp==3.14.3" in dependencies
    assert "aiohttp==3.12.15" not in dependencies
    assert "yarl==1.24.2" in dependencies


def test_public_repository_documentation_is_compact_and_excludes_internal_evidence_library() -> None:
    readme_lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    security_lines = (ROOT / "SECURITY.md").read_text(encoding="utf-8").splitlines()
    contributing_lines = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").splitlines()

    assert not (ROOT / "docs" / "evidence").exists()
    assert len(readme_lines) <= 120
    assert len(security_lines) <= 35
    assert len(contributing_lines) <= 35
