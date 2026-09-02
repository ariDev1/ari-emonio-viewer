from pathlib import Path


def test_stage3b_frontend_exposes_only_fixed_1w_simulated_action() -> None:
    api = Path("frontend/js/load-control-stage3b-api.js").read_text()
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text()

    assert "/api/v1/load-control/lan-simulated-test/status" in api
    assert "/api/v1/load-control/lan-simulated-test/send" in api
    assert "runSimulatedCommandTest" in api

    assert 'id="lc-simulated-run"' in ui
    assert "SEND 1 W SIMULATED TEST" in ui
    assert "PHASE A" in ui
    assert "NO PHYSICAL OUTPUT" in ui
    assert "ZERO RESET REQUIRED" in ui
    assert "safe_reset_required" in ui
    assert "runSimulatedCommandTest" in ui


def test_stage3b_frontend_does_not_offer_operator_wattage_or_phase_inputs() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text()

    assert 'id="lc-simulated-watts"' not in ui
    assert 'id="lc-simulated-phase"' not in ui
    assert "watts:" not in ui
