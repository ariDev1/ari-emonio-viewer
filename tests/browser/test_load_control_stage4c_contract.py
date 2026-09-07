from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "frontend/js/load-control-stage4c-api.js"
UI = ROOT / "frontend/js/load-control-stage4c-ui.js"
CSS = ROOT / "frontend/css/load-control/zero-export-controller.css"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"


def test_stage4c_frontend_exposes_only_required_operator_configuration() -> None:
    source = UI.read_text(encoding="utf-8")
    for field_id in (
        "lc-zec-source",
        "lc-zec-phase",
        "lc-zec-deadband",
        "lc-zec-configure",
        "lc-zec-enable",
        "lc-zec-disable",
        "lc-zec-state",
        "lc-zec-reason",
        "lc-zec-cycle",
        "lc-zec-p",
        "lc-zec-action",
        "lc-zec-confirmed-requested",
        "lc-zec-confirmed-actual",
        "lc-zec-confirmed-compare",
        "lc-zec-confirmed-period",
        "lc-zec-lower",
        "lc-zec-upper",
        "lc-zec-safe",
    ):
        assert field_id in source
    assert "Duty step" not in source
    assert "duty_step" not in source
    assert "p_target" not in source


def test_stage4c_ui_states_current_control_and_scientific_boundaries() -> None:
    source = UI.read_text(encoding="utf-8")
    for statement in (
        "Automatic physical PWM control is active when enabled",
        "Canonical signed P is the only measurement feedback input",
        "Target is fixed at 0 W",
        "No watts-to-duty calibration",
        "No Q or PF control",
        "No automatic reconnect",
        "requested-duty range is OFF 0 % and active 5–95 %",
        "timer-tick resolution",
        "LIMIT_LOW",
        "RESOLUTION_LIMIT",
        "SAFE_UNCONFIRMED",
    ):
        assert statement in source

    for obsolete in (
        "active 25–75 %",
        "25 % active minimum",
        "0↔25",
    ):
        assert obsolete not in source


def test_stage4c_operator_view_exposes_engineering_evidence() -> None:
    source = UI.read_text(encoding="utf-8")
    for field_id in (
        "lc-zec-deadband-evidence",
        "lc-zec-p-condition",
        "lc-zec-bracket-width",
        "lc-zec-timer-step",
        "lc-zec-command-suppressed",
        "lc-zec-state-explanation",
    ):
        assert field_id in source

    for heading in (
        "CONTROL CONDITION",
        "SEARCH BRACKET",
        "PWM PHYSICAL STATE",
        "STATE EXPLANATION",
    ):
        assert heading in source


def test_stage4c_operator_evidence_uses_dedicated_structured_css() -> None:
    css = CSS.read_text(encoding="utf-8")
    for selector in (
        ".load-control-zero-export-evidence",
        ".load-control-zero-export-evidence-card",
        ".load-control-zero-export-explanation",
    ):
        assert selector in css


def test_stage4c_uses_existing_safe_source_list() -> None:
    source = UI.read_text(encoding="utf-8")
    assert "getSafeTestSources" in source
    assert "Choose Emonio source" in source
    assert 'option value="A"' in source
    assert 'option value="B"' in source
    assert 'option value="C"' in source


def test_stage4c_api_client_exposes_zero_export_routes_only() -> None:
    source = API.read_text(encoding="utf-8")
    for route in (
        "/api/v1/load-control/zero-export/status",
        "/api/v1/load-control/zero-export/configure",
        "/api/v1/load-control/zero-export/enable",
        "/api/v1/load-control/zero-export/disable",
    ):
        assert route in source
    for forbidden in (
        "/lan-pwm/apply",
        "/lan-pwm/off",
        "/characterization/auto-sweep",
        "/p-observer/configure",
    ):
        assert forbidden not in source


def test_stage4c_frontend_has_no_direct_manual_pwm_hook() -> None:
    source = API.read_text(encoding="utf-8") + "\n" + UI.read_text(encoding="utf-8")
    for forbidden in (
        "applyManualPwmDuty",
        "turnManualPwmOff",
        "runExplicitSweep",
        "captureCurrentDuty",
    ):
        assert forbidden not in source


def test_stage4c_uses_dedicated_structured_css_and_loads_after_manual_pwm() -> None:
    css = CSS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert ".load-control-zero-export" in css
    assert "zero-export-controller.css" in app
    assert "load-control-stage4b-characterization-ui.js" not in app
    stage3b = app.index("load-control-stage3b-ui.js")
    stage4c = app.index("load-control-stage4c-ui.js")
    assert stage3b < stage4c
