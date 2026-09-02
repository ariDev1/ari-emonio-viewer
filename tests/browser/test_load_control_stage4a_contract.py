from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "frontend/js/load-control-stage4a-api.js"
UI = ROOT / "frontend/js/load-control-stage4a-ui.js"
CSS = ROOT / "frontend/css/load-control/p-control-observer.css"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"


def test_stage4a_frontend_files_exist_and_have_required_operator_fields() -> None:
    source = UI.read_text(encoding="utf-8")
    required_ids = {
        "lc-pobs-source",
        "lc-pobs-phase",
        "lc-pobs-target",
        "lc-pobs-deadband",
        "lc-pobs-step",
        "lc-pobs-configure",
        "lc-pobs-enable",
        "lc-pobs-disable",
        "lc-pobs-state",
        "lc-pobs-reason",
        "lc-pobs-cycle",
        "lc-pobs-p",
        "lc-pobs-q",
        "lc-pobs-quality",
        "lc-pobs-age",
        "lc-pobs-confirmed-requested",
        "lc-pobs-confirmed-actual",
        "lc-pobs-decision",
        "lc-pobs-proposed",
    }
    for field_id in required_ids:
        assert field_id in source


def test_stage4a_ui_states_scientific_and_output_boundaries() -> None:
    source = UI.read_text(encoding="utf-8")
    for statement in (
        "P is the only control variable",
        "Q is display-only",
        "No automatic PWM command is sent",
        "Apply a proposal manually",
    ):
        assert statement in source


def test_stage4a_frontend_has_no_pwm_output_hook() -> None:
    source = API.read_text(encoding="utf-8") + "\n" + UI.read_text(encoding="utf-8")
    for forbidden in (
        "applyManualPwmDuty",
        "turnManualPwmOff",
        "/lan-pwm/apply",
        "/lan-pwm/off",
        "APPLY PROPOSED",
    ):
        assert forbidden not in source


def test_stage4a_api_client_exposes_observer_routes_only() -> None:
    source = API.read_text(encoding="utf-8")
    for route in (
        "/api/v1/load-control/p-observer/status",
        "/api/v1/load-control/p-observer/configure",
        "/api/v1/load-control/p-observer/enable",
        "/api/v1/load-control/p-observer/disable",
        "/api/v1/load-control/p-observer/diagnostics",
    ):
        assert route in source


def test_stage4a_ui_distinguishes_null_proposal_from_valid_zero() -> None:
    source = UI.read_text(encoding="utf-8")
    assert 'value == null ? "—"' in source
    assert "toFixed(6)" in source
    assert "0.000000 %" in source


def test_stage4a_uses_dedicated_structured_css() -> None:
    source = CSS.read_text(encoding="utf-8")
    assert ".load-control-p-observer" in source
    assert "p-control-observer.css" in APP.read_text(encoding="utf-8")


def test_stage4a_script_loads_after_stage3b_script() -> None:
    source = APP.read_text(encoding="utf-8")
    stage3b = source.index("load-control-stage3b-ui.js")
    stage4a = source.index("load-control-stage4a-ui.js")
    assert stage3b < stage4a
