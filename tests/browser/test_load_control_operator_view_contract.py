from pathlib import Path


def test_load_control_panel_defaults_to_simple_operator_view() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")

    assert "OPERATOR VIEW" in ui
    assert "SIMULATION ONLY" in ui
    assert "<h3>Actuator</h3>" in ui
    assert "<h3>Emonio source</h3>" in ui
    assert "<h3>Safe state</h3>" in ui
    assert "SET SAFE 0 W" in ui

    assert '<details id="lc-engineering-diagnostics"' in ui
    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools" open>' not in ui
    assert "ENGINEERING DIAGNOSTICS" in ui

    engineering_index = ui.index("ENGINEERING DIAGNOSTICS")
    assert ui.index('id="lc-lan-discovery-window"') > engineering_index
    assert ui.index('id="lc-lan-resolve-timeout"') > engineering_index
    assert ui.index("Diagnostic log") > engineering_index
    assert ui.index("DEVELOPMENT / MOCK CONTROL") > engineering_index


def test_stage3b_panel_defaults_to_simple_simulated_action() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")

    assert "<h3>Simulated test</h3>" in ui
    assert "TEST 1 W — PHASE A" in ui
    assert "NO PHYSICAL OUTPUT" in ui
    assert "ZERO RESET REQUIRED" in ui
    assert "ENGINEERING DETAILS" in ui
    assert '<details class="load-control-engineering-inline">' in ui
    assert '<details class="load-control-engineering-inline" open>' not in ui

    engineering_index = ui.index("ENGINEERING DETAILS")
    assert ui.index("COMMAND sequence") > engineering_index
    assert ui.index("ACK result") > engineering_index
    assert ui.index("Rejection") > engineering_index
