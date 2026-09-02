from pathlib import Path


def test_load_control_ui_preserves_real_controls_and_collapsed_engineering_evidence() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    assert "OPERATOR VIEW" in ui
    assert "SIMULATION ONLY" in ui
    assert "NONZERO REAL CONTROL DISABLED" in ui
    assert "<h3>Actuator</h3>" in ui
    assert "<h3>Emonio source</h3>" in ui
    assert "<h3>Safe state</h3>" in ui
    assert "Diagnostic log" in ui
    assert "DEVELOPMENT / MOCK CONTROL" in ui

    actuator_heading = "<h3>Actuator</h3>"
    source_heading = "<h3>Emonio source</h3>"
    safe_heading = "<h3>Safe state</h3>"
    engineering_summary = "<summary>ENGINEERING DIAGNOSTICS</summary>"
    diagnostic_heading = "<h3>Diagnostic log</h3>"
    development_summary = "<summary>DEVELOPMENT / MOCK CONTROL</summary>"
    assert ui.index(actuator_heading) < ui.index(source_heading)
    assert ui.index(source_heading) < ui.index(safe_heading)
    assert ui.index(safe_heading) < ui.index(engineering_summary)
    assert ui.index(engineering_summary) < ui.index(diagnostic_heading)
    assert ui.index(diagnostic_heading) < ui.index(development_summary)

    assert 'id="lc-scan-lan"' in ui
    assert 'id="lc-real-actuator"' in ui
    assert "Choose discovered actuator" in ui
    assert 'id="lc-select-qualify"' in ui
    assert "CONNECT / QUALIFY" in ui
    assert 'id="lc-selected-actuator"' in ui
    assert 'id="lc-ws-state"' in ui
    assert 'id="lc-hello-state"' in ui
    assert 'id="lc-qualification-error"' in ui
    assert 'id="lc-qualification-disconnect"' in ui

    assert 'id="lc-safe-source"' in ui
    assert "Choose Emonio source" in ui
    assert 'id="lc-safe-select-source"' in ui
    assert "SELECT SOURCE" in ui
    assert 'id="lc-safe-run"' in ui
    assert "SET SAFE 0 W" in ui
    assert 'id="lc-safe-state"' in ui
    assert 'id="lc-safe-source-state"' in ui
    assert 'id="lc-safe-message"' in ui

    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools">' in ui
    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools" open>' not in ui
    engineering_index = ui.index("ENGINEERING DIAGNOSTICS")
    assert ui.index('id="lc-lan-discovery-window"') > engineering_index
    assert ui.index('id="lc-lan-resolve-timeout"') > engineering_index
    assert ui.index('id="lc-qualification-identity"') > engineering_index
    assert ui.index('id="lc-qualification-protocol"') > engineering_index
    assert ui.index('id="lc-qualification-limits"') > engineering_index
    assert ui.index('id="lc-qualification-location"') > engineering_index
    assert ui.index('id="lc-safe-cycle"') > engineering_index
    assert ui.index('id="lc-safe-sequence"') > engineering_index
    assert ui.index('id="lc-safe-ack"') > engineering_index
    assert ui.index('id="lc-safe-rejection"') > engineering_index
    assert "control_enabled=false" in ui
    assert "P request A/B/C = 0 W" in ui
    assert "Q request A/B/C = 0 var" in ui
    assert "No retry" in ui
    assert "No nonzero control" in ui

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
    assert "/api/v1/load-control/lan-safe-test/sources" in api
    assert "/api/v1/load-control/lan-safe-test/status" in api
    assert "/api/v1/load-control/lan-safe-test/source" in api
    assert "/api/v1/load-control/lan-safe-test/send" in api
    assert "/api/v1/load-control/safe-test/" not in api
    assert "/api/v1/load-control/lan-diagnostics/clear" not in api
    assert "/api/v1/load-control/command" not in api
    assert 'id="lc-command-a"' not in ui
    assert 'id="lc-command-b"' not in ui
    assert 'id="lc-command-c"' not in ui


def test_stage3a_frontend_requires_explicit_operator_actions_and_never_auto_runs() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")

    assert 'element("lc-safe-select-source").addEventListener("click", selectSafeSource);' in ui
    assert 'element("lc-safe-run").addEventListener("click", runSafeTest);' in ui
    assert "await selectSafeTestSource(deviceId)" in ui
    assert "await runSafeCommandTest()" in ui
    assert 'element("lc-safe-source").addEventListener("change",' not in ui

    interval_start = ui.index("setInterval(() =>")
    interval_source = ui[interval_start:]
    assert "runSafeTest()" not in interval_source
    assert "selectSafeSource()" not in interval_source
    assert "runSafeCommandTest()" not in interval_source
    assert "selectSafeTestSource(" not in interval_source

    assert "localStorage" not in ui
    assert "sessionStorage" not in ui


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
    assert '"/api/v1/load-control/lan-safe-test/sources"' in api
    assert '"/api/v1/load-control/lan-safe-test/status"' in api
    assert '"/api/v1/load-control/lan-safe-test/source"' in api
    assert '"/api/v1/load-control/lan-safe-test/send"' in api
    assert '"/api/v1/load-control/safe-test/' not in api
    assert '"/api/v1/load-control/binding"' in api
    assert '"/api/v1/load-control/config"' in api
    assert '"/api/v1/load-control/timing"' in api
    assert '"/api/v1/load-control/enable"' in api
    assert '"/api/v1/load-control/disable"' in api
