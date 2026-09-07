from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PANEL_CSS = ROOT / "frontend/css/panel-information.css"
PANEL_UI = ROOT / "frontend/js/right-panel-information.js"
DIAGNOSTICS_UI = ROOT / "frontend/js/diagnostics.js"
SERVER_APP = ROOT / "src/emonio_viewer/server/app_v0416.py"


def test_shared_right_panel_information_layer_is_loaded() -> None:
    css = PANEL_CSS.read_text(encoding="utf-8")
    ui = PANEL_UI.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS_UI.read_text(encoding="utf-8")

    assert 'from "./right-panel-information.js"' in diagnostics
    assert "initializeRightPanelInformation();" in diagnostics
    assert 'new URL("../css/panel-information.css", import.meta.url)' in ui
    for selector in (
        ".panel-purpose",
        ".panel-critical-boundary",
        ".panel-critical-boundary-item",
        ".panel-technical-boundary",
        ".panel-technical-boundary-body",
    ):
        assert selector in css


def test_static_right_panels_use_common_information_hierarchy() -> None:
    source = PANEL_UI.read_text(encoding="utf-8")

    for panel_id in (
        "diagnostics-drawer",
        "recording-drawer",
        "scope-drawer",
    ):
        assert panel_id in source

    for required in (
        "Shows runtime and device evidence for the selected Emonio.",
        "Manages session recording for the selected Emonio.",
        "Shows the Emonio waveform capture for selected phases and signals.",
        "VALID does not mean scientifically qualified.",
        "READ-ONLY DEVICE EVIDENCE",
        "RESET-ON-READ MIN/MAX REGISTERS ARE NOT READ",
        "This evidence is separate from the canonical U/I/P/Q/S/PF/f acquisition path.",
        "TELNET REQUIRED",
        "PHYSICAL CT ORIENTATION IS NOT VERIFIED",
        "P(t)=U[k]×I[k] IS SCOPE-DERIVED",
        "NOT CANONICAL MODBUS P",
        "NO SMOOTHING. NO AVERAGING. NO RESAMPLING.",
        "TECHNICAL BOUNDARY",
    ):
        assert required in source


def test_load_control_right_panel_uses_common_information_hierarchy() -> None:
    source = PANEL_UI.read_text(encoding="utf-8")

    for required in (
        "Connects one qualified actuator and runs the zero-export controller.",
        "PHYSICAL PWM COMMANDS",
        "QUALIFIED ACTUATOR",
        "OFF CONFIRMATION REQUIRED",
        "Finds, selects, and qualifies one compatible actuator.",
        "Provides manual PWM control and protocol evidence for engineering work.",
        "Shows backend LAN, WebSocket/HELLO, PWM command, ACK, and rejection evidence.",
    ):
        assert required in source


def test_manual_pwm_keeps_operator_boundary_visible_and_details_collapsed() -> None:
    source = PANEL_UI.read_text(encoding="utf-8")

    for required in (
        "Sends direct PWM duty commands to the qualified actuator.",
        "PHYSICAL PWM COMMANDS",
        "DO NOT USE WITH AUTOMATIC CONTROL",
        "This control does not use Emonio measurements.",
        "This control does not convert watts to duty.",
        "automatic zero-export control owns PWM authority",
    ):
        assert required in source


def test_zero_export_keeps_critical_operator_boundary_visible_and_science_preserved() -> None:
    source = PANEL_UI.read_text(encoding="utf-8")

    for required in (
        "Uses canonical signed P to drive the qualified actuator toward 0 W.",
        "AUTOMATIC PHYSICAL PWM CONTROL",
        "P ONLY",
        "OFF MUST BE CONFIRMED",
        "OFF 0 % · ACTIVE 5–95 %",
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


def test_information_layer_has_no_control_or_network_authority() -> None:
    source = PANEL_UI.read_text(encoding="utf-8")
    for forbidden in (
        "fetch(",
        "/api/",
        "applyManualPwmDuty",
        "turnManualPwmOff",
        "configureZeroExport",
        "enableZeroExport",
        "disableZeroExport",
        "MutationObserver",
        "setInterval",
    ):
        assert forbidden not in source


def test_inactive_stage4a_and_stage4b_ui_are_not_reintroduced() -> None:
    app = SERVER_APP.read_text(encoding="utf-8")
    assert "load-control-stage4a-ui.js" not in app
    assert "load-control-stage4b-characterization-ui.js" not in app
