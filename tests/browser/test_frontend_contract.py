from pathlib import Path


def test_frontend_has_fixed_phase_and_total_panels() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for element_id in ("phase-a", "phase-b", "phase-c", "phase-total"):
        assert f'id="{element_id}"' in html


def test_css_is_split_by_responsibility() -> None:
    css = Path("frontend/css")
    assert {p.name for p in css.glob("*.css")} == {
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


def test_frontend_contains_no_emonio_ip_or_modbus_socket_logic() -> None:
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path("frontend/js").glob("*.js"))
    assert "192.168." not in source
    assert ":502" not in source
    assert "build_read_holding_request" not in source
    assert "read_holding_registers" not in source
    assert "read_discrete_inputs" not in source
