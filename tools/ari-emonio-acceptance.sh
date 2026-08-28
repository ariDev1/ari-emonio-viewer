#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "ARI Emonio Viewer Acceptance"
echo "[1/6] Unit tests"
python3 -m pytest tests/unit -q

echo "[2/6] Integration tests"
python3 -m pytest tests/integration -q

echo "[3/6] Frontend contract"
python3 -m pytest tests/browser -q

echo "[4/6] Read-only source gate"
python3 -m pytest tests/unit/test_read_only_contract.py -q

echo "[5/6] Python compilation"
python3 -m compileall -q src tests

echo "[6/6] Scientific sign path"
python3 -m pytest tests/integration/test_end_to_end_sign.py -q

echo "ARI Emonio Viewer Acceptance: PASS"
