from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest


MODULE = Path("frontend/js/load-control-stage4c-evidence.js")


def _run_evidence_module(expression: str) -> object:
    if not MODULE.is_file():
        pytest.fail("Stage4C evidence module is not implemented")
    source = MODULE.read_text(encoding="utf-8")
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
const result = {expression};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_stage4c_evidence_derives_only_display_values_from_existing_status() -> None:
    result = _run_evidence_module(
        "mod.deriveStage4CEvidence({"
        "measured_p_w:-3.42,p_deadband_w:2.0,"
        "lower_bracket_duty_percent:27.4560546875,"
        "upper_bracket_duty_percent:27.5,"
        "confirmed_period_ticks:7619,state:'RESOLUTION_LIMIT'"
        "})"
    )

    assert result["deadbandW"] == 2.0
    assert result["pCondition"] == "EXPORT · INCREASE LOAD"
    assert result["bracketWidthPercent"] == pytest.approx(0.0439453125)
    assert result["timerStepPercent"] == pytest.approx(100.0 / 7619.0)
    assert result["commandSuppressed"] == "YES"


def test_stage4c_evidence_reports_hold_and_unknown_geometry_without_inference() -> None:
    result = _run_evidence_module(
        "mod.deriveStage4CEvidence({"
        "measured_p_w:-0.9,p_deadband_w:2.0,"
        "lower_bracket_duty_percent:null,upper_bracket_duty_percent:null,"
        "confirmed_period_ticks:null,state:'TARGET_BAND'"
        "})"
    )

    assert result == {
        "deadbandW": 2.0,
        "pCondition": "TARGET BAND · HOLD",
        "bracketWidthPercent": None,
        "timerStepPercent": None,
        "commandSuppressed": "NO",
    }


def test_stage4c_state_explanations_cover_operator_relevant_states() -> None:
    states = [
        "TARGET_BAND",
        "SETTLING",
        "LIMIT_LOW",
        "LIMIT_HIGH",
        "RESOLUTION_LIMIT",
        "BLOCKED_SAFE",
        "SAFE_UNCONFIRMED",
    ]
    result = _run_evidence_module(
        f"Object.fromEntries({json.dumps(states)}.map((state) => [state, mod.explainStage4CState({{state}})]))"
    )

    assert result == {
        "TARGET_BAND": "Canonical P is inside the configured deadband. HOLD is active and no PWM command is required.",
        "SETTLING": "The first causal post-ACK sample is reserved for settling. No control decision is made from this sample.",
        "LIMIT_LOW": "The low-authority boundary is active. Confirmed OFF is held and repeated OFF↔5 % commands are suppressed.",
        "LIMIT_HIGH": "The active maximum is reached. No higher active duty is qualified.",
        "RESOLUTION_LIMIT": "The requested adjustment produced no new physical PWM timer state. Further commands in the same direction are suppressed.",
        "BLOCKED_SAFE": "Control is blocked in a safe state. Check the reason and OFF evidence.",
        "SAFE_UNCONFIRMED": "OFF could not be confirmed. Automatic control is disabled and the actuator state requires operator attention.",
    }
