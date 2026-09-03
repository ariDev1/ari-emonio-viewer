from pathlib import Path


def test_manual_pwm_api_is_explicit_and_separate_from_power_requests() -> None:
    api = Path("frontend/js/load-control-stage3b-api.js").read_text(encoding="utf-8")

    assert "/api/v1/load-control/lan-pwm/status" in api
    assert "/api/v1/load-control/lan-pwm/apply" in api
    assert "/api/v1/load-control/lan-pwm/off" in api
    assert "getManualPwmStatus" in api
    assert "applyManualPwmDuty" in api
    assert "turnManualPwmOff" in api
    assert "duty_percent" in api
    assert "p_load_request" not in api


def test_manual_pwm_engineering_control_requires_current_pwm_qualification() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")

    assert 'element("lc-manual-pwm-slot")' in ui
    assert "Manual PWM duty" in ui
    assert "Duty [%]" in ui
    assert 'id="lc-pwm-apply"' in ui
    assert 'id="lc-pwm-off"' in ui
    assert "APPLY DUTY" in ui
    assert "OFF" in ui
    assert "PWM_DUTY_CONTROL" in ui
    assert "qualificationStatus?.connected" in ui
    assert "qualificationStatus?.hello_qualified" in ui
    assert 'qualificationStatus?.capabilities?.includes(PWM_DUTY_CONTROL_CAPABILITY)' in ui
    assert "getManualPwmStatus" in ui
    assert "applyManualPwmDuty" in ui
    assert "turnManualPwmOff" in ui


def test_manual_pwm_engineering_control_shows_quantized_ack_evidence_and_has_structured_css() -> None:
    ui = Path("frontend/js/load-control-stage3b-ui.js").read_text(encoding="utf-8")
    css = Path("frontend/css/load-control/load-control.css").read_text(encoding="utf-8")

    assert "Requested duty" in ui
    assert "Actual duty" in ui
    assert "Compare ticks" in ui
    assert "Period ticks" in ui
    assert "actual_duty_percent" in ui
    assert "compare_ticks" in ui
    assert "period_ticks" in ui
    assert ".load-control-pwm-control" in css
    assert ".load-control-pwm-input" in css
