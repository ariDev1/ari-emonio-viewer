from __future__ import annotations

from pathlib import Path
import tomllib

from emonio_viewer import __version__


def test_v037_candidate_release_identity_is_consistent() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.3.7"
    assert __version__ == "0.3.7"

def test_v037_candidate_readme_release_status_is_current() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "trusted field baseline is **v0.3.3**" in readme
    assert "**v0.3.7 Candidate**" in readme
    assert "trusted field baseline remains **v0.2.9**" not in readme
    assert "v0.3.3 is the current development Candidate" not in readme
