from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "frontend/js/load-control-stage4a-api.js"
UI = ROOT / "frontend/js/load-control-stage4a-ui.js"
CSS = ROOT / "frontend/css/load-control/p-control-observer.css"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"


def test_stage4a_engineering_files_and_api_are_preserved() -> None:
    source = UI.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "P Control Observer" in source
    assert "P is the only control variable" in source
    assert "Q is display-only" in source
    assert "No automatic PWM command is sent" in source
    assert ".load-control-p-observer" in css
    for route in (
        "/api/v1/load-control/p-observer/status",
        "/api/v1/load-control/p-observer/configure",
        "/api/v1/load-control/p-observer/enable",
        "/api/v1/load-control/p-observer/disable",
        "/api/v1/load-control/p-observer/diagnostics",
    ):
        assert route in api


def test_stage4a_observer_is_not_loaded_into_active_operator_ui() -> None:
    app = APP.read_text(encoding="utf-8")

    assert "load-control-stage4a-ui.js" not in app
    assert "p-control-observer.css" not in app
    assert "register_load_control_stage4a_routes(app)" in app
    assert "PControlObserverService" in app


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
