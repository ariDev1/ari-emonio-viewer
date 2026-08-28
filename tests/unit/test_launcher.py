from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = PROJECT_ROOT / "start-emonio-viewer.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_launcher_exists_is_executable_and_has_valid_bash_syntax() -> None:
    assert LAUNCHER.is_file()
    assert os.access(LAUNCHER, os.X_OK)
    result = subprocess.run(
        ["bash", "-n", str(LAUNCHER)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_launcher_help_is_available_without_setup() -> None:
    result = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd="/",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "start-emonio-viewer.sh" in result.stdout
    assert "--no-browser" in result.stdout
    assert "--config" in result.stdout


def test_launcher_is_linux_portable_and_has_no_distro_package_manager() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    forbidden_commands = ("sudo", "pacman", "apt", "apt-get", "dnf", "zypper")
    executable_lines = [line.strip() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    for command in forbidden_commands:
        assert not any(line == command or line.startswith(f"{command} ") for line in executable_lines)
    assert "xdg-open" in source
    assert "python3" in source


def test_launcher_creates_venv_installs_once_and_starts_from_its_own_directory(tmp_path: Path) -> None:
    project = tmp_path / "viewer project"
    project.mkdir()
    shutil.copy2(LAUNCHER, project / LAUNCHER.name)
    (project / LAUNCHER.name).chmod((project / LAUNCHER.name).stat().st_mode | stat.S_IXUSR)
    (project / "config").mkdir()
    (project / "config" / "emonio-viewer.toml").write_text("[viewer]\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='test-viewer'\nversion = \"0.0.0\"\n", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    log = tmp_path / "launcher.log"

    fake_python = fake_bin / "python3"
    _write_executable(
        fake_python,
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "system-python:$*" >> "$EMONIO_LAUNCHER_TEST_LOG"
            if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
                venv_dir="$3"
                mkdir -p "$venv_dir/bin"
                cat > "$venv_dir/bin/python" <<'EOF'
            #!/usr/bin/env bash
            set -euo pipefail
            echo "venv-python:$*" >> "$EMONIO_LAUNCHER_TEST_LOG"
            exit 0
            EOF
                chmod +x "$venv_dir/bin/python"
                cat > "$venv_dir/bin/emonio-viewer" <<'EOF'
            #!/usr/bin/env bash
            set -euo pipefail
            echo "viewer:$*" >> "$EMONIO_LAUNCHER_TEST_LOG"
            exit 0
            EOF
                chmod +x "$venv_dir/bin/emonio-viewer"
                exit 0
            fi
            exit 2
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["EMONIO_LAUNCHER_TEST_LOG"] = str(log)

    command = [str(project / LAUNCHER.name), "--no-browser"]
    first = subprocess.run(command, cwd="/", env=env, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr

    second = subprocess.run(command, cwd="/", env=env, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr

    lines = log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("system-python:-m venv ") for line in lines) == 1
    assert sum("venv-python:-m pip install" in line for line in lines) == 1
    viewer_lines = [line for line in lines if line.startswith("viewer:")]
    assert len(viewer_lines) == 2
    expected_config = project / "config" / "emonio-viewer.toml"
    assert all(f"--config {expected_config}" in line for line in viewer_lines)


def test_launcher_reports_virtual_environment_creation_failure(tmp_path: Path) -> None:
    project = tmp_path / "viewer"
    project.mkdir()
    shutil.copy2(LAUNCHER, project / LAUNCHER.name)
    (project / LAUNCHER.name).chmod((project / LAUNCHER.name).stat().st_mode | stat.S_IXUSR)
    (project / "config").mkdir()
    (project / "config" / "emonio-viewer.toml").write_text("[viewer]\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='test-viewer'\nversion = \"0.0.0\"\n", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "python3",
        "#!/usr/bin/env bash\nexit 17\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [str(project / LAUNCHER.name), "--no-browser"],
        cwd="/",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "could not create the local Python environment" in result.stderr


def test_launcher_opens_release_versioned_document_url() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'VIEWER_URL_BASE="http://127.0.0.1:8787"' in source
    assert 'APP_VERSION=' in source
    assert 'VIEWER_URL="${VIEWER_URL_BASE}/?v=${APP_VERSION}"' in source
