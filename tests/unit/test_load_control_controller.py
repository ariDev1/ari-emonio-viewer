import math

import pytest

from emonio_viewer.load_control.controller import (
    calculate_phase_request,
    calculate_three_phase_request,
)
from emonio_viewer.load_control.model import ThreePhasePower


def test_export_from_zero_load_requests_450_w():
    result = calculate_phase_request(
        measured_p=-420.0,
        p_reserve=30.0,
        acknowledged_p=0.0,
        p_limit=1000.0,
    )
    assert result.error == 450.0
    assert result.raw_request == 450.0
    assert result.limited_request == 450.0
    assert result.limited_min is False
    assert result.limited_max is False


def test_next_request_uses_acknowledged_applied_state():
    result = calculate_phase_request(
        measured_p=25.0,
        p_reserve=30.0,
        acknowledged_p=450.0,
        p_limit=1000.0,
    )
    assert result.error == 5.0
    assert result.raw_request == 455.0
    assert result.limited_request == 455.0


def test_negative_raw_request_clamps_to_zero():
    result = calculate_phase_request(
        measured_p=250.0,
        p_reserve=30.0,
        acknowledged_p=100.0,
        p_limit=1000.0,
    )
    assert result.raw_request == -120.0
    assert result.limited_request == 0.0
    assert result.limited_min is True
    assert result.limited_max is False


def test_maximum_saturation_is_visible_without_hidden_command_state():
    result = calculate_phase_request(
        measured_p=-900.0,
        p_reserve=30.0,
        acknowledged_p=0.0,
        p_limit=600.0,
    )
    assert result.raw_request == 930.0
    assert result.limited_request == 600.0
    assert result.limited_min is False
    assert result.limited_max is True


def test_three_phase_calculation_is_phase_independent():
    result = calculate_three_phase_request(
        measured_p=ThreePhasePower(a=-420.0, b=25.0, c=100.0),
        p_reserve=30.0,
        acknowledged_p=ThreePhasePower(a=0.0, b=450.0, c=50.0),
        p_limit=ThreePhasePower(a=600.0, b=700.0, c=800.0),
    )
    assert result.a.limited_request == 450.0
    assert result.b.limited_request == 455.0
    assert result.c.limited_request == 0.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_phase_calculation_rejects_non_finite_inputs(bad):
    with pytest.raises(ValueError):
        calculate_phase_request(
            measured_p=bad,
            p_reserve=30.0,
            acknowledged_p=0.0,
            p_limit=600.0,
        )
