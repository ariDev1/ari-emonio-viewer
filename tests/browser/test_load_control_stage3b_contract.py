from pathlib import Path


def test_stage3b_simulated_api_is_preserved_but_not_exposed_in_operator_ui() -> None:
    api = Path("frontend/js/load-control-stage3b-api.js").read_text(encoding="utf-8")
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")

    assert "/api/v1/load-control/lan-simulated-test/status" in api
    assert "/api/v1/load-control/lan-simulated-test/send" in api
    assert "runSimulatedCommandTest" in api

    for obsolete in (
        'id="lc-simulated-run"',
        "TEST 1 W — PHASE A",
        "NO PHYSICAL OUTPUT",
        "ZERO RESET REQUIRED",
        "safe_reset_required",
        "runSimulatedCommandTest",
        "getSimulatedTestStatus",
    ):
        assert obsolete not in ui


def test_stage3b_ui_is_manual_pwm_engineering_control_only() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")

    assert 'element("lc-manual-pwm-slot")' in ui
    assert "Manual PWM duty" in ui
    assert 'id="lc-pwm-duty"' in ui
    assert 'id="lc-pwm-apply"' in ui
    assert 'id="lc-pwm-off"' in ui
    assert "APPLY DUTY" in ui
    assert "PWM ACK DETAILS" in ui
    assert 'element("lc-simulated-operator-slot")' not in ui
