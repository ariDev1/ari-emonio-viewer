import inspect

import pytest

from emonio_viewer.load_control.zero_export import (
    ZeroExportAction,
    calculate_zero_export_step,
)


def test_off_with_negative_p_enters_active_window_at_25_percent() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=-40.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert decision.action is ZeroExportAction.INCREASE
    assert decision.next_duty_percent == 25.0
    assert decision.lower_bracket_duty_percent is None
    assert decision.upper_bracket_duty_percent is None


def test_negative_p_without_upper_bracket_moves_by_midpoint_to_upper_limit() -> None:
    first = calculate_zero_export_step(
        measured_p_w=-40.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert first.action is ZeroExportAction.INCREASE
    assert first.next_duty_percent == 50.0
    assert first.lower_bracket_duty_percent == 25.0

    second = calculate_zero_export_step(
        measured_p_w=-20.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=50.0,
        lower_bracket_duty_percent=first.lower_bracket_duty_percent,
        upper_bracket_duty_percent=first.upper_bracket_duty_percent,
    )
    assert second.next_duty_percent == 62.5
    assert second.lower_bracket_duty_percent == 50.0


def test_opposite_sign_creates_bracket_and_bisects_it() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=8.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=62.5,
        lower_bracket_duty_percent=50.0,
        upper_bracket_duty_percent=None,
    )
    assert decision.action is ZeroExportAction.DECREASE
    assert decision.lower_bracket_duty_percent == 50.0
    assert decision.upper_bracket_duty_percent == 62.5
    assert decision.next_duty_percent == 56.25


def test_inside_deadband_holds_without_changing_bracket() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=-1.5,
        p_deadband_w=2.0,
        confirmed_duty_percent=56.25,
        lower_bracket_duty_percent=50.0,
        upper_bracket_duty_percent=62.5,
    )
    assert decision.action is ZeroExportAction.HOLD
    assert decision.next_duty_percent == 56.25
    assert decision.lower_bracket_duty_percent == 50.0
    assert decision.upper_bracket_duty_percent == 62.5


def test_positive_p_at_minimum_active_duty_commands_explicit_off() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=5.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert decision.action is ZeroExportAction.DECREASE
    assert decision.next_duty_percent == 0.0


def test_positive_p_while_off_stays_explicitly_off() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=5.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        lower_bracket_duty_percent=None,
        upper_bracket_duty_percent=None,
    )
    assert decision.action is ZeroExportAction.SAFE_OFF
    assert decision.next_duty_percent == 0.0


def test_negative_p_at_75_percent_reports_high_limit_without_command_change() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=-100.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=75.0,
        lower_bracket_duty_percent=60.0,
        upper_bracket_duty_percent=None,
    )
    assert decision.action is ZeroExportAction.LIMIT_HIGH
    assert decision.next_duty_percent == 75.0


def test_changed_load_invalidates_stale_upper_bracket() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=-12.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=60.0,
        lower_bracket_duty_percent=40.0,
        upper_bracket_duty_percent=50.0,
    )
    assert decision.action is ZeroExportAction.INCREASE
    assert decision.lower_bracket_duty_percent == 60.0
    assert decision.upper_bracket_duty_percent is None
    assert decision.next_duty_percent == 67.5


def test_changed_load_invalidates_stale_lower_bracket() -> None:
    decision = calculate_zero_export_step(
        measured_p_w=12.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=40.0,
        lower_bracket_duty_percent=50.0,
        upper_bracket_duty_percent=70.0,
    )
    assert decision.action is ZeroExportAction.DECREASE
    assert decision.lower_bracket_duty_percent is None
    assert decision.upper_bracket_duty_percent == 40.0
    assert decision.next_duty_percent == 32.5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"measured_p_w": float("nan")},
        {"p_deadband_w": -0.1},
        {"confirmed_duty_percent": 10.0},
        {"confirmed_duty_percent": 100.0},
        {"lower_bracket_duty_percent": float("inf")},
        {"upper_bracket_duty_percent": -1.0},
    ],
)
def test_invalid_inputs_fail_closed(kwargs: dict[str, float]) -> None:
    values = {
        "measured_p_w": -10.0,
        "p_deadband_w": 2.0,
        "confirmed_duty_percent": 25.0,
        "lower_bracket_duty_percent": None,
        "upper_bracket_duty_percent": None,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        calculate_zero_export_step(**values)


def test_zero_export_calculator_has_no_q_pf_or_watt_to_duty_gain_input() -> None:
    parameters = set(inspect.signature(calculate_zero_export_step).parameters)
    assert parameters == {
        "measured_p_w",
        "p_deadband_w",
        "confirmed_duty_percent",
        "lower_bracket_duty_percent",
        "upper_bracket_duty_percent",
    }
    assert "q" not in " ".join(parameters).lower()
    assert "pf" not in " ".join(parameters).lower()
    assert "gain" not in " ".join(parameters).lower()
