from pathlib import Path


def test_load_control_ui_prioritizes_real_stage2_connection_and_copyable_diagnostics() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    assert "STAGE 2 · NETWORK QUALIFICATION" in ui
    assert "REAL CONTROL DISABLED" in ui
    assert "Actuator connection" in ui
    assert "Qualification" in ui
    assert "Diagnostic log" in ui
    assert "DEVELOPMENT / MOCK CONTROL" in ui
    connection_heading = "<h3>Actuator connection</h3>"
    qualification_heading = "<h3>Qualification</h3>"
    diagnostic_heading = "<h3>Diagnostic log</h3>"
    development_summary = "<summary>DEVELOPMENT / MOCK CONTROL</summary>"
    assert ui.index(connection_heading) < ui.index(qualification_heading)
    assert ui.index(qualification_heading) < ui.index(diagnostic_heading)
    assert ui.index(diagnostic_heading) < ui.index(development_summary)

    assert 'id="lc-lan-discovery-window"' in ui
    assert 'id="lc-lan-resolve-timeout"' in ui
    assert 'id="lc-scan-lan"' in ui
    assert 'id="lc-real-actuator"' in ui
    assert "Choose discovered actuator" in ui
    assert 'id="lc-select-qualify"' in ui
    assert "CONNECT / QUALIFY" in ui
    assert 'id="lc-selected-actuator"' in ui

    assert 'id="lc-ws-state"' in ui
    assert 'id="lc-hello-state"' in ui
    assert 'id="lc-qualification-identity"' in ui
    assert 'id="lc-qualification-protocol"' in ui
    assert 'id="lc-qualification-limits"' in ui
    assert 'id="lc-qualification-location"' in ui
    assert 'id="lc-qualification-error"' in ui
    assert 'id="lc-qualification-disconnect"' in ui

    assert 'id="lc-diagnostic-log"' in ui
    assert 'id="lc-copy-diagnostic-log"' in ui
    assert 'id="lc-clear-diagnostic-view"' in ui
    assert "COPY LOG" in ui
    assert "CLEAR VIEW" in ui
    assert "backend-owned" in ui
    assert "does not delete the backend log" in ui

    assert '<details id="lc-development-tools" class="load-control-development-tools">' in ui
    assert '<details id="lc-development-tools" class="load-control-development-tools" open>' not in ui
    assert "ENABLE MOCK CONTROL" in ui

    assert "/api/v1/load-control/lan-discovery/scan" in api
    assert "/api/v1/load-control/lan-qualification/connect" in api
    assert "/api/v1/load-control/lan-qualification/status" in api
    assert "/api/v1/load-control/lan-qualification/disconnect" in api
    assert "/api/v1/load-control/lan-diagnostics/log" in api
    assert "/api/v1/load-control/lan-diagnostics/clear" not in api
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
    assert '"/api/v1/load-control/lan-discovery/scan"' in api
    assert '"/api/v1/load-control/lan-qualification/connect"' in api
    assert '"/api/v1/load-control/lan-qualification/status"' in api
    assert '"/api/v1/load-control/lan-qualification/disconnect"' in api
    assert '"/api/v1/load-control/lan-diagnostics/log"' in api
    assert '"/api/v1/load-control/binding"' in api
    assert '"/api/v1/load-control/config"' in api
    assert '"/api/v1/load-control/timing"' in api
    assert '"/api/v1/load-control/enable"' in api
    assert '"/api/v1/load-control/disable"' in api
