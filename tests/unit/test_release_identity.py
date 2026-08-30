from __future__ import annotations

from pathlib import Path
import tomllib

from emonio_viewer import __version__


def test_v0413_candidate_release_identity_is_consistent() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.4.13"
    assert __version__ == "0.4.13"
    pkg_info = Path("src/ari_emonio_viewer.egg-info/PKG-INFO").read_text(encoding="utf-8")
    assert "Version: 0.4.13" in pkg_info


def test_v0413_readme_keeps_v0412_as_trusted_field_baseline() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "trusted field baseline is **v0.4.12**" in readme
    assert "**v0.4.13 Candidate**" in readme
    assert "trusted field baseline is **v0.4.13**" not in readme
