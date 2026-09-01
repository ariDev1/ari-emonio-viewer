from __future__ import annotations

from pathlib import Path
import tomllib

from emonio_viewer import __version__


def test_v0420_testing_release_identity_is_consistent() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.4.20"
    assert project["project"]["scripts"]["emonio-viewer"] == "emonio_viewer.main_v0416:main"
    assert __version__ == "0.4.20"
    pkg_info = Path("src/ari_emonio_viewer.egg-info/PKG-INFO").read_text(encoding="utf-8")
    assert "Version: 0.4.20" in pkg_info


def test_v0420_readme_keeps_v0414_as_trusted_release_baseline() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "trusted field baseline is **v0.4.14**" in readme
    assert "**v0.4.20 Testing**" in readme
    assert "Negative-Condition Monitor" in readme
    assert "trusted field baseline is **v0.4.20**" not in readme
