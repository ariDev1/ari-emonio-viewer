#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$PROJECT_ROOT/tools/publication_gate.py" --staged
