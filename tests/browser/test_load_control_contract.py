from pathlib import Path


def test_load_control_ui_keeps_actuator_and_collapsed_engineering_tools_only() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    assert "OPERATOR VIEW" in ui
    assert "QUALIFIED PWM CONTROL" in ui
    assert "<h3>Actuator</h3>" in ui
    assert 'id="lc-zero-export-slot"' in ui
    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools">' in ui
    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools" open>' not in ui

    engineering_index = ui.index("ENGINEERING DIAGNOSTICS")
    assert ui.index('id="lc-manual-pwm-slot"') > engineering_index
    assert ui.index('id="lc-characterization-slot"') > engineering_index
    assert ui.index('id="lc-lan-discovery-window"') > engineering_index
    assert ui.index('id="lc-lan-resolve-timeout"') > engineering_index
    assert ui.index('id="lc-qualification-identity"') > engineering_index
    assert ui.index('id="lc-qualification-protocol"') > engineering_index
    assert ui.index('id="lc-qualification-limits"') > engineering_index
    assert ui.index('id="lc-qualification-location"') > engineering_index
    assert ui.index('id="lc-diagnostic-log"') > engineering_index
    assert ui.index('id="lc-copy-diagnostic-log"') > engineering_index
    assert ui.index('id="lc-clear-diagnostic-view"') > engineering_index

    for obsolete in (
        'id="lc-safe-source"',
        'id="lc-safe-select-source"',
        'id="lc-safe-run"',
        'id="lc-safe-state"',
        'id="lc-development-tools"',
        "ENABLE MOCK CONTROL",
        "SIMULATION ONLY",
        "NONZERO REAL CONTROL DISABLED",
    ):
        assert obsolete not in ui

    assert "/api/v1/load-control/lan-discovery/scan" in api
    assert "/api/v1/load-control/lan-qualification/connect" in api
    assert "/api/v1/load-control/lan-qualification/status" in api
    assert "/api/v1/load-control/lan-qualification/disconnect" in api
    assert "/api/v1/load-control/lan-diagnostics/log" in api
    assert "/api/v1/load-control/lan-safe-test/sources" in api
    assert "/api/v1/load-control/command" not in api
    assert 'id="lc-command-a"' not in ui
    assert 'id="lc-command-b"' not in ui
    assert 'id="lc-command-c"' not in ui


def test_operator_ui_does_not_call_legacy_safe_or_mock_actions() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")

    for obsolete in (
        "selectSafeTestSource",
        "runSafeCommandTest",
        "enableLoadControl",
        "disableLoadControl",
        "setLoadControlBinding",
        "setLoadControlLimits",
        "setLoadControlTiming",
        "getLoadControlStatus",
        "getRecentLoadControlEvidence",
    ):
        assert obsolete not in ui

    assert "localStorage" not in ui
    assert "sessionStorage" not in ui


def test_load_control_frontend_uses_its_own_structured_files() -> None:
    assert Path("frontend/css/load-control/load-control.css").is_file()
    assert Path("frontend/js/load-control-api.js").is_file()
    assert Path("frontend/js/load-control-ui.js").is_file()


def test_active_v0416_app_keeps_load_control_backend_routes() -> None:
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
    assert '"/api/v1/load-control/binding"' in api
    assert '"/api/v1/load-control/config"' in api
    assert '"/api/v1/load-control/timing"' in api
    assert '"/api/v1/load-control/enable"' in api
    assert '"/api/v1/load-control/disable"' in api
