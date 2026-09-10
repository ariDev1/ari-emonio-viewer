from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest


MODEL_PATH = Path("frontend/js/load-control-stage4c-history.js")
UI_PATH = Path("frontend/js/load-control-stage4c-history-ui.js")
CSS_PATH = Path("frontend/css/load-control/control-history.css")


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


def test_ui_has_explicit_follow_and_press_lock_cursor_modes() -> None:
    if not UI_PATH.is_file():
        pytest.fail("Stage4C Control History UI is not implemented")
    source = UI_PATH.read_text(encoding="utf-8")

    assert "selectionLocked" in source
    assert "controlEvidenceForSequence" in source
    assert "FOLLOWING POINTER" in source
    assert "LOCKED" in source
    assert "CLICK AGAIN TO FOLLOW" in source
    assert "dataset.sequence" in source


def test_visible_markers_use_separate_enlarged_pointer_hit_targets() -> None:
    source = UI_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    assert "appendEvidenceHitTarget" in source
    assert "control-history-hit-target" in source
    assert 'target.dataset.sequence = String(sequence)' in source
    assert ".control-history-hit-target" in css
    assert "pointer-events: stroke" in css
    assert "stroke-width: 12px" in css


def test_locked_marker_press_moves_lock_and_same_marker_press_releases_it() -> None:
    source = UI_PATH.read_text(encoding="utf-8")

    assert "sameLockedSequence" in source
    assert "state.selectionLocked = !sameLockedSequence" in source
    assert "if (state.selectionLocked) return" in source


def test_control_history_uses_semantic_scientific_colors_and_selection_outline() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    source = UI_PATH.read_text(encoding="utf-8")

    assert "--control-history-p: var(--accent)" in css
    assert "--control-history-request: var(--warning)" in css
    assert "--control-history-confirmed: var(--good)" in css
    assert "--control-history-danger: var(--danger)" in css
    assert ".control-history-event-warning" in css
    assert ".control-history-event-danger" in css
    assert ".control-history-evidence-marker.is-selected" in css
    assert "controlHistoryEventClass" in source
    assert "renderSelectionHighlight" in source


def test_interaction_is_delegated_to_stable_history_section_before_redraw_can_cancel_click() -> None:
    source = UI_PATH.read_text(encoding="utf-8")

    assert "function bindHistoryInspection(section)" in source
    assert 'section.dataset.controlHistoryInspectionBound === "true"' in source
    assert 'section.dataset.controlHistoryInspectionBound = "true"' in source
    assert 'section.addEventListener("pointermove"' in source
    assert 'section.addEventListener("pointerdown"' in source
    assert 'svg.addEventListener("click"' not in source
    assert 'svg.addEventListener("pointermove"' not in source


def test_exact_browser_target_sequence_precedes_geometric_fallback() -> None:
    source = UI_PATH.read_text(encoding="utf-8")

    assert "function evidenceSequenceFromTarget(target)" in source
    assert 'target?.closest?.("[data-sequence]")' in source
    assert "function historyPlotFromTarget(target)" in source
    assert 'target?.closest?.(".control-history-plot")' in source
    assert "nearestVisibleEvidenceSequence" in source
    assert 'querySelectorAll(".control-history-evidence-marker")' in source
    assert "marker.getBoundingClientRect()" in source
    assert "Math.hypot" in source
    assert "event.clientX" in source
    assert "event.clientY" in source
    exact = source.index("const exactSequence = evidenceSequenceFromTarget(event.target)")
    fallback = source.index("const nearestSequence = nearestVisibleEvidenceSequence(event, svg)")
    assert exact < fallback


def test_existing_and_new_history_dom_bind_the_stable_section_once() -> None:
    source = UI_PATH.read_text(encoding="utf-8")

    assert 'const existing = element("lc-zec-control-history")' in source
    assert "if (existing)" in source
    assert "bindHistoryInspection(existing);" in source
    assert "bindHistoryInspection(section);" in source
