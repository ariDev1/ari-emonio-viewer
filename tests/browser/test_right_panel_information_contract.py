from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "frontend/index.html"
PANEL_CSS = ROOT / "frontend/css/panel-information.css"
LOAD_CONTROL_UI = ROOT / "frontend/js/load-control-ui.js"
MANUAL_PWM_UI = ROOT / "frontend/js/load-control-stage3b-ui.js"
ZERO_EXPORT_UI = ROOT / "frontend/js/load-control-stage4c-ui.js"


def test_shared_right_panel_information_styles_are_loaded() -> None:
    index = INDEX.read_text(encoding="utf-8")
    css = PANEL_CSS.read_text(encoding="utf-8")

    assert 'href="/static/css/panel-information.css"' in index
    for selector in (
        ".panel-purpose",
        ".panel-critical-boundary",
        ".panel-critical-boundary-item",
        ".panel-technical-boundary",
        ".panel-technical-boundary-body",
    ):
        assert selector in css


def test_static_right_panels_use_common_information_hierarchy() -> None:
    source = INDEX.read_text(encoding="utf-8")

    for panel_id in (
        "diagnostics-drawer",
        "recording-drawer",
        "scope-drawer",
    ):
        panel_start = source.index(f'id="{panel_id}"')
        panel_source = source[panel_start:]
        assert 'class="panel-purpose"' in panel_source

    for required in (
        "VALID does not mean scientifically qualified",
        "READ-ONLY DEVICE EVIDENCE",
        "RESET-ON-READ MIN/MAX REGISTERS ARE NOT READ",
        "This evidence is separate from the canonical U/I/P/Q/S/PF/f acquisition path",
        "TELNET REQUIRED",
        "PHYSICAL CT ORIENTATION IS NOT VERIFIED",
        "P(t)=U[k]×I[k]",
        "NOT CANONICAL MODBUS P",
        "NO SMOOTHING",
        "NO AVERAGING",
        "NO RESAMPLING",
    ):
        assert required in source

    assert source.count("TECHNICAL BOUNDARY") >= 4


def test_load_control_right_panel_uses_common_information_hierarchy() -> None:
    source = LOAD_CONTROL_UI.read_text(encoding="utf-8")

    assert 'class="panel-purpose"' in source
    assert 'class="panel-critical-boundary"' in source
    assert "PHYSICAL PWM COMMANDS" in source
    assert "QUALIFIED ACTUATOR" in source
    assert "OFF CONFIRMATION REQUIRED" in source
    assert "ENGINEERING DIAGNOSTICS" in source


def test_manual_pwm_keeps_operator_boundary_visible_and_details_collapsed() -> None:
    source = MANUAL_PWM_UI.read_text(encoding="utf-8")

    for required in (
        'class="panel-purpose"',
        'class="panel-critical-boundary"',
        "PHYSICAL PWM COMMANDS",
        "DO NOT USE WITH AUTOMATIC CONTROL",
        "TECHNICAL BOUNDARY",
        "does not use Emonio measurements",
        "does not convert watts to duty",
    ):
        assert required in source


def test_zero_export_keeps_critical_operator_boundary_visible_and_science_preserved() -> None:
    source = ZERO_EXPORT_UI.read_text(encoding="utf-8")

    for required in (
        'class="panel-purpose"',
        'class="panel-critical-boundary"',
        "AUTOMATIC PHYSICAL PWM CONTROL",
        "P ONLY",
        "OFF MUST BE CONFIRMED",
        "OFF 0 % · ACTIVE 5–95 %",
        "TECHNICAL BOUNDARY",
        "Canonical signed P is the only measurement feedback input",
        "Target is fixed at 0 W",
        "No watts-to-duty calibration",
        "No Q or PF control",
        "No automatic reconnect",
        "LIMIT_LOW",
        "RESOLUTION_LIMIT",
        "SAFE_UNCONFIRMED",
    ):
        assert required in source
