from pathlib import Path


def test_stage3a_frontend_uses_approved_operator_wording_and_routes() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    assert "NONZERO REAL CONTROL DISABLED" in ui
    assert "SET SAFE 0 W" in ui
    assert "P request A/B/C = 0 W" in ui
    assert "Q request A/B/C = 0 var" in ui
    assert "control_enabled=false" in ui
    assert "No retry" in ui

    assert "/api/v1/load-control/lan-safe-test/sources" in api
    assert "/api/v1/load-control/lan-safe-test/status" in api
    assert "/api/v1/load-control/lan-safe-test/source" in api
    assert "/api/v1/load-control/lan-safe-test/send" in api

    assert "/api/v1/load-control/safe-test/sources" not in api
    assert "/api/v1/load-control/safe-test/status" not in api
    assert "/api/v1/load-control/safe-test/source" not in api
    assert "/api/v1/load-control/safe-test/run" not in api
    assert "RUN SAFE 0 W TEST" not in ui
