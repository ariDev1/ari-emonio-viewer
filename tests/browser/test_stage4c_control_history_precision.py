from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


MODEL_PATH = Path("frontend/js/load-control-stage4c-history.js")
UI_PATH = Path("frontend/js/load-control-stage4c-history-ui.js")


def _run_model(expression: str) -> object:
    source = MODEL_PATH.read_text(encoding="utf-8")
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
console.log(JSON.stringify({expression}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_numeric_evidence_helper_never_converts_null_boolean_or_text_to_zero() -> None:
    result = _run_model(
        "[mod.finiteEvidenceNumber(null), mod.finiteEvidenceNumber(undefined), mod.finiteEvidenceNumber(false), mod.finiteEvidenceNumber('5'), mod.finiteEvidenceNumber(0), mod.finiteEvidenceNumber(5.25)]"
    )
    assert result == [None, None, None, None, 0, 5.25]


def test_explicit_null_ack_evidence_remains_unavailable() -> None:
    event = {
        "sequence": 90,
        "utc": "2026-09-08T07:00:00Z",
        "event": "PWM_ACK_QUALIFIED",
        "line": "x",
        "fields": {
            "owner": "STAGE4C_ZERO_EXPORT",
            "requested_duty_percent": 5.0,
            "actual_duty_percent": None,
            "compare_ticks": None,
            "period_ticks": None,
        },
    }
    result = _run_model(f"mod.deriveControlHistorySeries([{json.dumps(event)}]).acks[0]")
    assert result["requestedDutyPercent"] == 5.0
    assert result["actualDutyPercent"] is None
    assert result["compareTicks"] is None
    assert result["periodTicks"] is None
    assert result["isOff"] is False


def test_history_ui_module_parses_as_ecmascript_module() -> None:
    source = UI_PATH.read_text(encoding="utf-8")
    completed = subprocess.run(
        ["node", "--input-type=module", "--check"],
        input=source,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
