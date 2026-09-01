from pathlib import Path


def test_frontend_exposes_explicit_acquisition_lifecycle_controls() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")

    assert 'id="acquisition-state"' in html
    assert 'id="device-lifecycle-action"' in html
    assert "disconnectDevice" in api
    assert "reconnectDevice" in api
    assert "CONNECTED / EXISTING" not in app
    assert "DISCONNECT EMONIO" in app
    assert "RECONNECT EMONIO" in app


def test_lifecycle_api_preserves_structured_failure_payload() -> None:
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")

    assert "lifecycleRequest" in api
    assert "error.lifecycleResult" in api
    assert "/disconnect" in api
    assert "/reconnect" in api


def test_lifecycle_frontend_keeps_structured_css_file_set() -> None:
    css = Path("frontend/css")
    assert {path.name for path in css.glob("*.css")} == {
        "base.css",
        "layout.css",
        "phase-panels.css",
        "quadrant.css",
        "diagnostics.css",
        "recording.css",
        "ct-evidence.css",
        "history.css",
        "scope.css",
        "modbus-evidence.css",
        "density.css",
        "recording-monitor.css",
        "load-control.css",
    }


def test_lifecycle_state_mapping_and_disconnected_selector_are_explicit() -> None:
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")

    for token in (
        "RUNNING",
        "DISCONNECTED",
        "DISCONNECTING",
        "CONNECTING",
        "ERROR",
        "DISCONNECTING...",
        "CONNECTING...",
        "DISCONNECT ERROR",
        "· DISCONNECTED",
    ):
        assert token in app
