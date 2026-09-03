from pathlib import Path


def test_stage3a_safe_api_is_preserved_but_retired_from_operator_ui() -> None:
    ui = Path("frontend/js/load-control-ui.js").read_text(encoding="utf-8")
    api = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")

    for retired in (
        "NONZERO REAL CONTROL DISABLED",
        "SET SAFE 0 W",
        "P request A/B/C = 0 W",
        "Q request A/B/C = 0 var",
        "control_enabled=false",
        "RUN SAFE 0 W TEST",
    ):
        assert retired not in ui

    assert "/api/v1/load-control/lan-safe-test/sources" in api
    assert "/api/v1/load-control/lan-safe-test/status" in api
    assert "/api/v1/load-control/lan-safe-test/source" in api
    assert "/api/v1/load-control/lan-safe-test/send" in api

    assert "/api/v1/load-control/safe-test/sources" not in api
    assert "/api/v1/load-control/safe-test/status" not in api
    assert "/api/v1/load-control/safe-test/source" not in api
    assert "/api/v1/load-control/safe-test/run" not in api
