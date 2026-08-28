#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$PROJECT_ROOT/.venv"
PYPROJECT="$PROJECT_ROOT/pyproject.toml"
INSTALL_MARKER="$VENV_DIR/.emonio-viewer-pyproject"
DEFAULT_CONFIG="$PROJECT_ROOT/config/emonio-viewer.toml"
VIEWER_URL_BASE="http://127.0.0.1:8787"
SYSTEM_PYTHON="${EMONIO_PYTHON:-python3}"
OPEN_BROWSER=1
CONFIG_PATH="$DEFAULT_CONFIG"

usage() {
    cat <<'EOF'
Usage: ./start-emonio-viewer.sh [options]

Start the ARI Emonio Viewer from this project directory.

Options:
  --config PATH     Use a specific TOML configuration file.
  --no-browser      Do not open the local viewer in the default browser.
  -h, --help        Show this help text.

The launcher creates .venv on first start and installs the runtime package
only when setup is required. It does not require sudo or a distro-specific
package manager.
EOF
}

while (($#)); do
    case "$1" in
        --config)
            if (($# < 2)); then
                echo "ARI Emonio Viewer launcher: ERROR: --config requires a path" >&2
                exit 2
            fi
            CONFIG_PATH="$2"
            shift 2
            ;;
        --no-browser)
            OPEN_BROWSER=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ARI Emonio Viewer launcher: ERROR: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! -f "$PYPROJECT" ]]; then
    echo "ARI Emonio Viewer launcher: ERROR: pyproject.toml not found in $PROJECT_ROOT" >&2
    exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "ARI Emonio Viewer launcher: ERROR: configuration not found: $CONFIG_PATH" >&2
    exit 1
fi

APP_VERSION="$(awk -F'"' '/^version = "/ {print $2; exit}' "$PYPROJECT")"
if [[ -z "$APP_VERSION" ]]; then
    echo "ARI Emonio Viewer launcher: ERROR: application version is missing from pyproject.toml" >&2
    exit 1
fi
VIEWER_URL="${VIEWER_URL_BASE}/?v=${APP_VERSION}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    if ! command -v "$SYSTEM_PYTHON" >/dev/null 2>&1; then
        echo "ARI Emonio Viewer launcher: ERROR: Python 3 was not found." >&2
        echo "Install Python 3.10 or newer, then run this launcher again." >&2
        exit 1
    fi

    echo "[ARI Emonio Viewer] Creating local Python environment..."
    if ! "$SYSTEM_PYTHON" -m venv "$VENV_DIR"; then
        echo "ARI Emonio Viewer launcher: ERROR: could not create the local Python environment." >&2
        echo "Verify that Python 3.10 or newer includes venv support, then run again." >&2
        exit 1
    fi
fi

SETUP_REQUIRED=0
if [[ ! -x "$VENV_DIR/bin/emonio-viewer" ]]; then
    SETUP_REQUIRED=1
elif [[ ! -f "$INSTALL_MARKER" ]]; then
    SETUP_REQUIRED=1
elif ! cmp -s "$PYPROJECT" "$INSTALL_MARKER"; then
    SETUP_REQUIRED=1
fi

if ((SETUP_REQUIRED)); then
    echo "[ARI Emonio Viewer] Installing runtime dependencies..."
    if ! "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_ROOT"; then
        echo "ARI Emonio Viewer launcher: ERROR: package installation failed." >&2
        echo "Check the network connection and Python environment, then run again." >&2
        exit 1
    fi
    cp "$PYPROJECT" "$INSTALL_MARKER"
fi

if [[ ! -x "$VENV_DIR/bin/emonio-viewer" ]]; then
    echo "ARI Emonio Viewer launcher: ERROR: viewer executable is missing after setup." >&2
    exit 1
fi

if ((OPEN_BROWSER)) && command -v xdg-open >/dev/null 2>&1; then
    (
        "$VENV_DIR/bin/python" - "$VIEWER_URL" <<'PY'
from __future__ import annotations

import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

url = sys.argv[1]
deadline = time.monotonic() + 15.0
while time.monotonic() < deadline:
    try:
        with urlopen(url, timeout=0.5):
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            raise SystemExit(0)
    except (URLError, TimeoutError, OSError):
        time.sleep(0.2)
PY
    ) >/dev/null 2>&1 &
fi

echo "[ARI Emonio Viewer] Starting scientific measurement viewer..."
echo "[ARI Emonio Viewer] Device configuration: $CONFIG_PATH"
echo "[ARI Emonio Viewer] Local viewer: $VIEWER_URL"
echo "[ARI Emonio Viewer] Stop with Ctrl+C"

exec "$VENV_DIR/bin/emonio-viewer" --config "$CONFIG_PATH"
