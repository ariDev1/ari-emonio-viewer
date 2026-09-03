from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "frontend/js/load-control-stage4b-characterization-api.js"
UI = ROOT / "frontend/js/load-control-stage4b-characterization-ui.js"
CSS = ROOT / "frontend/css/load-control/p-characterization.css"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"


def test_stage4b_frontend_files_exist_and_expose_engineering_controls() -> None:
    source = UI.read_text(encoding="utf-8")
    assert 'element("lc-characterization-slot")' in source
    for field_id in (
        "lc-pchar-source",
        "lc-pchar-phase",
        "lc-pchar-duties",
        "lc-pchar-manual-capture",
        "lc-pchar-auto-sweep",
        "lc-pchar-state",
        "lc-pchar-mode",
        "lc-pchar-progress",
        "lc-pchar-current-duty",
        "lc-pchar-settling",
        "lc-pchar-measured",
        "lc-pchar-safe",
        "lc-pchar-error",
        "lc-pchar-results",
    ):
        assert field_id in source
    assert 'element("lc-simulated-operator-slot")' not in source


def test_stage4b_ui_states_exact_scientific_and_physical_boundaries() -> None:
    source = UI.read_text(encoding="utf-8")
    for statement in (
        "Physical PWM commands are sent",
        "P is the only characterized measurement",
        "signed canonical P",
        "2 settling cycles",
        "3 measured cycles",
        "25–75 %",
        "Final OFF = 0 % must be acknowledged",
        "No PID or regulator is active",
    ):
        assert statement in source


def test_stage4b_uses_existing_source_list_and_explicit_sweep_points() -> None:
    source = UI.read_text(encoding="utf-8")
    assert "getSafeTestSources" in source
    assert "parseExplicitDuties" in source
    assert "RUN EXPLICIT SWEEP" in source
    assert "CAPTURE CURRENT DUTY" in source
    assert "duties: parseExplicitDuties" in source


def test_stage4b_results_show_command_identity_and_signed_p_statistics() -> None:
    source = UI.read_text(encoding="utf-8")
    for field in (
        "requested_duty_percent",
        "actual_duty_percent",
        "command_sequence",
        "cycle_ids",
        "p_samples_w",
        "mean_p_w",
        "min_p_w",
        "max_p_w",
        "sample_stdev_p_w",
        "utc",
    ):
        assert field in source


def test_stage4b_api_client_exposes_characterization_routes_only() -> None:
    source = API.read_text(encoding="utf-8")
    for route in (
        "/api/v1/load-control/characterization/status",
        "/api/v1/load-control/characterization/manual-capture",
        "/api/v1/load-control/characterization/auto-sweep",
    ):
        assert route in source
    for forbidden in (
        "/p-observer/configure",
        "/lan-pwm/apply",
        "/lan-pwm/off",
    ):
        assert forbidden not in source


def test_stage4b_uses_dedicated_css_and_loads_as_collapsed_engineering_tool() -> None:
    css = CSS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert ".load-control-p-characterization" in css
    assert "p-characterization.css" in app
    assert "load-control-stage4b-characterization-ui.js" in app
    assert "load-control-stage4a-ui.js" not in app
    stage3b = app.index("load-control-stage3b-ui.js")
    stage4b = app.index("load-control-stage4b-characterization-ui.js")
    stage4c = app.index("load-control-stage4c-ui.js")
    assert stage3b < stage4b < stage4c
