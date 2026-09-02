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
        "lc-zec-lower",
        "lc-zec-upper",
        "lc-zec-safe",
    ):
        assert field_id in source
    assert "Duty step" not in source
    assert "duty_step" not in source
    assert "p_target" not in source


def test_stage4c_ui_states_control_and_scientific_boundaries() -> None:
    source = UI.read_text(encoding="utf-8")
    for statement in (
        "Automatic physical PWM control is active when enabled",
        "Canonical signed P is the only feedback input",
        "Target is fixed at 0 W",
        "No watts-to-duty calibration",
        "No Q or PF control",
        "No automatic reconnect",
        "OFF 0 %",
        "active 25–75 %",
        "SAFE_UNCONFIRMED",
    ):
        assert statement in source


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


def test_stage4c_uses_dedicated_structured_css_and_loads_after_stage4b() -> None:
    css = CSS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert ".load-control-zero-export" in css
    assert "zero-export-controller.css" in app
    stage4b = app.index("load-control-stage4b-characterization-ui.js")
    stage4c = app.index("load-control-stage4c-ui.js")
    assert stage4b < stage4c
