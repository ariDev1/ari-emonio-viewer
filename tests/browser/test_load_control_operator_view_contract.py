from pathlib import Path
import re


def test_load_control_panel_defaults_to_zero_export_operator_view() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")

    assert "OPERATOR VIEW" in ui
    assert "QUALIFIED PWM CONTROL" in ui
    assert "<h3>Actuator</h3>" in ui
    assert 'id="lc-zero-export-slot"' in ui

    for obsolete in (
        "SIMULATION ONLY",
        "NONZERO REAL CONTROL DISABLED",
        "<h3>Emonio source</h3>",
        "<h3>Safe state</h3>",
        "SET SAFE 0 W",
        "DEVELOPMENT / MOCK CONTROL",
        "ENABLE MOCK CONTROL",
    ):
        assert obsolete not in ui

    assert '<details id="lc-engineering-diagnostics"' in ui
    assert '<details id="lc-engineering-diagnostics" class="load-control-engineering-tools" open>' not in ui
    engineering_index = ui.index("ENGINEERING DIAGNOSTICS")
    assert ui.index('id="lc-manual-pwm-slot"') > engineering_index
    assert ui.index('id="lc-characterization-slot"') > engineering_index
    assert ui.index("Diagnostic log") > engineering_index
    assert ui.index('id="lc-zero-export-slot"') < engineering_index


def test_stage3b_ui_exposes_manual_pwm_only_inside_engineering_diagnostics() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")

    assert "Manual PWM duty" in ui
    assert 'element("lc-manual-pwm-slot")' in ui
    assert 'id="lc-pwm-apply"' in ui
    assert 'id="lc-pwm-off"' in ui

    for obsolete in (
        "<h3>Simulated test</h3>",
        "TEST 1 W — PHASE A",
        "NO PHYSICAL OUTPUT",
        "ZERO RESET REQUIRED",
        "runSimulatedCommandTest",
        "lc-simulated-run",
    ):
        assert obsolete not in ui


def test_operator_view_uses_semantic_colors_for_actuator_state_only() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    css = Path("frontend/css/load-control/load-control.css").read_text(encoding="utf-8")

    assert "function setStatusTone" in ui
    assert re.search(r'setStatusTone\(\s*"lc-ws-state"', ui)
    assert re.search(r'setStatusTone\(\s*"lc-hello-state"', ui)
    assert "lc-safe-source-state" not in ui
    assert "lc-safe-state" not in ui
    assert "lc-readiness" not in ui

    assert '[data-tone="ok"]' in css
    assert '[data-tone="warn"]' in css
    assert '[data-tone="error"]' in css
