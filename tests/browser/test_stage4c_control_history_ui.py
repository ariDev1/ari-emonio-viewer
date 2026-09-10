from pathlib import Path

import pytest


UI_PATH = Path("frontend/js/load-control-stage4c-history-ui.js")
CSS_PATH = Path("frontend/css/load-control/control-history.css")


def _required_text(path: Path, label: str) -> str:
    if not path.is_file():
        pytest.fail(f"{label} is not implemented: {path}")
    return path.read_text(encoding="utf-8")


def test_control_history_ui_has_hard_read_only_authority_boundary() -> None:
    source = _required_text(UI_PATH, "Stage4C Control History UI")

    assert 'getLanDiagnosticLog' in source
    assert 'from "./load-control-api.js"' in source
    assert 'from "./load-control-stage4c-history.js"' in source

    for prohibited in (
        "configureZeroExport",
        "enableZeroExport",
        "disableZeroExport",
        "runManualPwm",
        "runReservedPwm",
        'method: "POST"',
        'method: \'POST\'',
        "/configure",
        "/enable",
        "/disable",
        "fetch(",
        "localStorage",
        "sessionStorage",
    ):
        assert prohibited not in source


def test_control_history_ui_states_observational_boundary_and_builds_three_synchronized_plots() -> None:
    source = _required_text(UI_PATH, "Stage4C Control History UI")

    for text in (
        "OBSERVATIONAL CONTROL EVIDENCE",
        "DOES NOT CONTROL THE ACTUATOR",
        "CANONICAL P REMAINS THE CONTROL INPUT",
        "MEASUREMENT → DECISION → PWM COMMAND → PWM ACK → SETTLING → MEASUREMENT",
    ):
        assert text in source

    for element_id in (
        "lc-zec-history-p-plot",
        "lc-zec-history-pwm-plot",
        "lc-zec-history-event-plot",
        "lc-zec-history-inspector",
        "lc-zec-history-utc",
        "lc-zec-history-local",
        "lc-zec-history-diagnostic-utc",
        "lc-zec-history-sequence-gaps",
    ):
        assert f'id="{element_id}"' in source

    assert "nearestControlEvidence" in source
    assert "deriveControlHistorySeries" in source
    assert "CONTROL_HISTORY_WINDOW_MS" in source
    assert "CONTROL_HISTORY_MAX_RECORDS" in source
    assert "pointermove" in source
    assert "pointerdown" in source
    assert "control-history-cursor" in source
    assert "style=" not in source
    assert "<button" not in source


def test_control_history_does_not_recalculate_canonical_p_or_access_modbus() -> None:
    model = Path("frontend/js/load-control-stage4c-history.js").read_text(encoding="utf-8")
    ui = _required_text(UI_PATH, "Stage4C Control History UI")
    combined = model + "\n" + ui

    assert "measured_p_w" in model
    for prohibited in (
        "phase_a",
        "phase_b",
        "phase_c",
        "read_holding",
        "read_discrete",
        ":502",
        "MODBUS_TCP",
        "calculate_zero_export_step",
    ):
        assert prohibited not in combined


def test_control_history_uses_dedicated_structured_css_and_active_app_injection() -> None:
    css = _required_text(CSS_PATH, "Stage4C Control History CSS")
    app = Path("src/emonio_viewer/server/app_v0416.py").read_text(encoding="utf-8")

    assert "load-control-control-history" in css
    assert "control-history-plot" in css
    assert "control-history-inspector" in css
    assert "control-history-cursor" in css
    assert "control-history.css" in app
    assert "load-control-stage4c-history-ui.js" in app


def test_control_history_inspector_exposes_only_evidence_fields_and_time_domains() -> None:
    source = _required_text(UI_PATH, "Stage4C Control History UI")

    for label in (
        "Canonical P / W",
        "Requested duty / %",
        "Actual duty / %",
        "Compare ticks",
        "Controller state",
        "Action",
        "Reason",
        "Cycle",
        "Monotonic finish / ns",
    ):
        assert label in source

    assert "Diagnostic UTC" in source
    assert "Local time" in source
    assert "UNAVAILABLE" in source
    assert "carryForward" not in source
    assert "lastKnown" not in source
