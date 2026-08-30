from pathlib import Path


def test_recording_drawer_has_multi_session_dashboard_and_selected_device_controls() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    for element_id in (
        "recording-dashboard-active",
        "recording-dashboard-records",
        "recording-dashboard-missed",
        "recording-dashboard-errors",
        "recording-session-grid",
        "recording-error-grid",
        "recording-drawer-selected-state",
        "recording-drawer-interval",
        "recording-drawer-start",
        "recording-drawer-stop",
    ):
        assert f'id="{element_id}"' in html


def test_recording_dashboard_exposes_per_session_stop_control_without_inline_handlers() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert 'button.dataset.recordingStopDevice = record.device_id;' in source
    assert 'await stopRecording(deviceId);' in source
    assert "onclick=" not in html


def test_recording_dashboard_uses_structured_recording_css() -> None:
    css = Path("frontend/css/recording.css").read_text(encoding="utf-8")

    for selector in (
        ".recording-dashboard-summary",
        ".recording-session-grid",
        ".recording-session-card",
        ".recording-session-metrics",
        ".recording-selected-controls",
    ):
        assert selector in css
