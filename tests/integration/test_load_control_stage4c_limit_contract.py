from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/emonio_viewer/load_control/zero_export_service.py"
CALCULATOR = ROOT / "src/emonio_viewer/load_control/zero_export.py"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"
API = ROOT / "src/emonio_viewer/server/load_control_stage4c_api.py"
UI = ROOT / "frontend/js/load-control-stage4c-ui.js"


def test_stage4c_has_explicit_low_authority_and_pwm_resolution_limits() -> None:
    calculator = CALCULATOR.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    assert 'LIMIT_LOW = "LIMIT_LOW"' in calculator
    assert 'RESOLUTION_LIMIT = "RESOLUTION_LIMIT"' in calculator
    assert 'LIMIT_LOW = "LIMIT_LOW"' in service
    assert 'RESOLUTION_LIMIT = "RESOLUTION_LIMIT"' in service
    assert '"LOW_AUTHORITY_LIMIT"' in service
    assert '"PWM_RESOLUTION_LIMIT"' in service


def test_stage4c_uses_shared_load_control_diagnostic_log() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "LoadControlDiagnosticLog" in service
    assert "ZERO_EXPORT_DECISION" in service
    assert "ZERO_EXPORT_LIMIT_LOW" in service
    assert "ZERO_EXPORT_RESOLUTION_LIMIT" in service
    assert "ZERO_EXPORT_SAFE_BLOCK" in service
    assert "diagnostic_log=qualification_service.diagnostic_log" in app


def test_stage4c_status_exposes_physical_pwm_tick_evidence() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")
    for name in ("confirmed_compare_ticks", "confirmed_period_ticks"):
        assert name in service
        assert name in api
    assert "lc-zec-confirmed-compare" in ui
    assert "lc-zec-confirmed-period" in ui
    assert "requested-duty range" in ui
    assert "timer-tick" in ui
    assert "LIMIT_LOW" in ui
    assert "RESOLUTION_LIMIT" in ui
