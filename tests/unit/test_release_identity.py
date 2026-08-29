from __future__ import annotations

from pathlib import Path
import tomllib

from emonio_viewer import __version__


def test_v043_release_identity_is_consistent() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.4.3"
    assert __version__ == "0.4.3"

def test_v043_readme_release_status_is_current() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "trusted field baseline is **v0.4.3**" in readme
    assert "**v0.4.3 Candidate**" not in readme
    assert "trusted field baseline remains **v0.2.9**" not in readme
    assert "v0.3.3 is the current development Candidate" not in readme
