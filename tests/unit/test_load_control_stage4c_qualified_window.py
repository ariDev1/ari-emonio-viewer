import pytest

from emonio_viewer.load_control.zero_export import (
    ACTIVE_DUTY_MAX_PERCENT,
    ACTIVE_DUTY_MIN_PERCENT,
    SAFE_OFF_DUTY_PERCENT,
    ZeroExportAction,
    calculate_zero_export_step,
)


def test_stage4c_uses_field_qualified_5_to_95_percent_active_window() -> None:
    assert SAFE_OFF_DUTY_PERCENT == 0.0
    assert ACTIVE_DUTY_MIN_PERCENT == 5.0
    assert ACTIVE_DUTY_MAX_PERCENT == 95.0

    from_off = calculate_zero_export_step(
        measured_p_w=-20.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert from_off.action is ZeroExportAction.INCREASE
    assert from_off.next_duty_percent == 5.0

    at_low_limit = calculate_zero_export_step(
        measured_p_w=5.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=5.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert at_low_limit.action is ZeroExportAction.LIMIT_LOW
    assert at_low_limit.next_duty_percent == 0.0

    at_high_limit = calculate_zero_export_step(
        measured_p_w=-20.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=95.0,
        lower_bracket_duty_percent=90.0,
        upper_bracket_duty_percent=None,
    )
    assert at_high_limit.action is ZeroExportAction.LIMIT_HIGH
    assert at_high_limit.next_duty_percent == 95.0


def test_stage4c_rejects_unqualified_nonzero_duty_below_5_percent() -> None:
    with pytest.raises(ValueError):
        calculate_zero_export_step(
            measured_p_w=-20.0,
            p_deadband_w=2.0,
            confirmed_duty_percent=4.999,
            lower_bracket_duty_percent=None,
            upper_bracket_duty_percent=None,
        )
