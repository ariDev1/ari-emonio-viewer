from pathlib import Path


def test_load_control_ui_is_explicitly_mock_only_and_has_no_direct_phase_command_inputs() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    assert "STAGE 1 · MOCK ACTUATOR ONLY" in ui
    assert "No mDNS, real WebSocket actuator, ESP32, PWM, or physical power-stage output is active." in ui
    assert "ENABLE EXTERNAL CONTROL" in ui
    assert "SAFE_UNCONFIRMED" in ui
    assert "/api/v1/load-control/enable" in api
    assert "/api/v1/load-control/disable" in api
    assert "/api/v1/load-control/command" not in api
    assert 'id="lc-command-a"' not in ui
    assert 'id="lc-command-b"' not in ui
    assert 'id="lc-command-c"' not in ui


def test_load_control_frontend_uses_its_own_structured_files() -> None:
    assert Path("frontend/css/load-control/load-control.css").is_file()
    assert Path("frontend/js/load-control-api.js").is_file()
    assert Path("frontend/js/load-control-ui.js").is_file()


def test_active_v0416_app_injects_load_control_assets_and_routes() -> None:
    app = Path("src/emonio_viewer/server/app_v0416.py").read_text(encoding="utf-8")
    api = Path("src/emonio_viewer/server/load_control_api.py").read_text(encoding="utf-8")

    assert "css/load-control/load-control.css" in app
    assert "load-control-ui.js" in app
    assert "register_load_control_routes(app)" in app
    assert '"/api/v1/load-control/status"' in api
    assert '"/api/v1/load-control/binding"' in api
    assert '"/api/v1/load-control/config"' in api
    assert '"/api/v1/load-control/timing"' in api
    assert '"/api/v1/load-control/enable"' in api
    assert '"/api/v1/load-control/disable"' in api
