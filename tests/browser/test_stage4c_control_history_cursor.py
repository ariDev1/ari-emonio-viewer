from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest


MODEL_PATH = Path("frontend/js/load-control-stage4c-history.js")
UI_PATH = Path("frontend/js/load-control-stage4c-history-ui.js")


def _run_model(expression: str) -> object:
    if not MODEL_PATH.is_file():
        pytest.fail("Stage4C control history model is not implemented")
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


def test_exact_marker_sequence_selects_that_record_without_nearest_time_reinterpretation() -> None:
    events = [
        {
            "sequence": 70,
            "utc": "2026-09-08T07:00:02.100Z",
            "event": "ZERO_EXPORT_DECISION",
            "line": "x",
            "fields": {
                "cycle_finished_utc": "2026-09-08T07:00:02.000Z",
                "measured_p_w": -20.0,
            },
        },
        {
            "sequence": 71,
            "utc": "2026-09-08T07:00:02.001Z",
            "event": "PWM_COMMAND_SENT",
            "line": "x",
            "fields": {
                "owner": "STAGE4C_ZERO_EXPORT",
                "requested_duty_percent": 5.0,
            },
        },
    ]
    result = _run_model(f"mod.controlEvidenceForSequence({json.dumps(events)}, 70)")
    assert result["sequence"] == 70
    assert result["event"] == "ZERO_EXPORT_DECISION"
    assert result["utc"] == "2026-09-08T07:00:02.000Z"
    assert result["diagnosticUtc"] == "2026-09-08T07:00:02.100Z"


def test_ui_has_explicit_follow_and_click_lock_cursor_modes() -> None:
    if not UI_PATH.is_file():
        pytest.fail("Stage4C Control History UI is not implemented")
    source = UI_PATH.read_text(encoding="utf-8")

    assert "selectionLocked" in source
    assert "controlEvidenceForSequence" in source
    assert "FOLLOWING POINTER" in source
    assert "LOCKED" in source
    assert "CLICK AGAIN TO FOLLOW" in source
    assert "event.target" in source
    assert "dataset.sequence" in source
