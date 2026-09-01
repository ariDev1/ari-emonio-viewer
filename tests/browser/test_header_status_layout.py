from __future__ import annotations

from pathlib import Path


def test_status_header_excludes_redundant_target_item() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert '<span class="status-label">Target</span>' not in html
    assert 'id="device-ip"' not in html


def test_measurement_renderer_has_no_removed_device_ip_write() -> None:
    source = Path("frontend/js/measurements.js").read_text(encoding="utf-8")
    assert 'getElementById("device-ip")' not in source


def test_application_controller_has_no_removed_device_ip_write() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert 'getElementById("device-ip")' not in source


def test_status_header_grid_has_eight_measurement_status_columns() -> None:
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(8, max-content);" in css
    assert "grid-template-columns: repeat(9, minmax(62px, auto));" not in css
