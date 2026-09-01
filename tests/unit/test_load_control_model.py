import math

import pytest

from emonio_viewer.load_control.model import (
    ControlMode,
    LoadControlTiming,
    PersistentLoadControlConfig,
    SafeState,
    SessionState,
    ThreePhasePower,
)


def test_three_phase_power_preserves_phase_mapping():
    value = ThreePhasePower(a=1.0, b=2.0, c=3.0)
    assert (value.a, value.b, value.c) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_persistent_config_rejects_invalid_reserve(bad):
    with pytest.raises(ValueError):
        PersistentLoadControlConfig(p_reserve=bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_timing_rejects_invalid_sample_age(bad):
    with pytest.raises(ValueError):
        LoadControlTiming(control_sample_max_age_s=bad, ack_timeout_s=1.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_timing_rejects_invalid_ack_timeout(bad):
    with pytest.raises(ValueError):
        LoadControlTiming(control_sample_max_age_s=1.0, ack_timeout_s=bad)


def test_state_enums_match_approved_three_domain_model():
    assert tuple(item.value for item in ControlMode) == ("DISABLED", "ENABLED", "TRIPPED")
    assert tuple(item.value for item in SessionState) == (
        "UNBOUND",
        "DISCOVERING",
        "UNAVAILABLE",
        "CONNECTING",
        "VERIFYING",
        "READY",
        "SESSION_FAULT",
    )
    assert tuple(item.value for item in SafeState) == (
        "NOT_REQUIRED",
        "SAFE_UNCONFIRMED",
        "SAFE_CONFIRMED",
    )
