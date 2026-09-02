import math

import pytest

from emonio_viewer.load_control.automatic_observation import (
    PControlDecision,
    calculate_p_control_proposal,
)


def test_increase_from_off_starts_at_25_percent() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-60.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 25.0
    assert result.low_w == -2.0
    assert result.high_w == 2.0


def test_increase_uses_one_step() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-15.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 30.0


def test_target_band_holds_confirmed_duty() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-1.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=40.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.HOLD
    assert result.proposed_duty_percent == 40.0


def test_decrease_from_25_percent_proposes_off() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=5.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.DECREASE
    assert result.proposed_duty_percent == 0.0


def test_confirmed_75_percent_is_high_limit() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=75.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_HIGH
    assert result.proposed_duty_percent == 75.0


def test_confirmed_off_is_low_limit_when_less_load_is_required() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_LOW
    assert result.proposed_duty_percent == 0.0


def test_reaching_75_percent_from_below_is_still_increase() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=70.0,
        duty_step_percent=10.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 75.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measured_p_w", math.nan),
        ("p_target_w", math.inf),
        ("p_deadband_w", -math.inf),
        ("confirmed_duty_percent", math.nan),
        ("duty_step_percent", math.inf),
    ],
)
def test_non_finite_inputs_are_rejected(field: str, value: float) -> None:
    kwargs = {
        "measured_p_w": -10.0,
        "p_target_w": 0.0,
        "p_deadband_w": 2.0,
        "confirmed_duty_percent": 25.0,
        "duty_step_percent": 5.0,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        calculate_p_control_proposal(**kwargs)


def test_negative_deadband_is_rejected() -> None:
    with pytest.raises(ValueError, match="p_deadband_w"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=-0.1,
            confirmed_duty_percent=25.0,
            duty_step_percent=5.0,
        )


@pytest.mark.parametrize("step", [0.0, -0.1])
def test_non_positive_step_is_rejected(step: float) -> None:
    with pytest.raises(ValueError, match="duty_step_percent"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=2.0,
            confirmed_duty_percent=25.0,
            duty_step_percent=step,
        )


@pytest.mark.parametrize("duty", [0.1, 24.999, 75.001, 90.0])
def test_unqualified_confirmed_duty_is_rejected(duty: float) -> None:
    with pytest.raises(ValueError, match="confirmed_duty_percent"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=2.0,
            confirmed_duty_percent=duty,
            duty_step_percent=5.0,
        )
