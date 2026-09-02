import math

import pytest

from emonio_viewer.load_control.characterization import (
    ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT,
    ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT,
    build_characterization_point,
    validate_sweep_duties,
)


def test_characterization_active_window_is_current_field_qualified_range() -> None:
    assert ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT == 25.0
    assert ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT == 75.0


def test_validate_sweep_duties_preserves_explicit_order() -> None:
    assert validate_sweep_duties([25, 35, 30, 75]) == (25.0, 35.0, 30.0, 75.0)


@pytest.mark.parametrize(
    "duties",
    [
        [],
        [25.0],
        [24.999, 30.0],
        [25.0, 75.001],
        [25.0, math.nan],
        [25.0, 25.0],
    ],
)
def test_validate_sweep_duties_rejects_invalid_lists(duties) -> None:
    with pytest.raises(ValueError):
        validate_sweep_duties(duties)


def test_validate_sweep_duties_rejects_more_than_51_points() -> None:
    duties = [25.0 + (50.0 * index / 51.0) for index in range(52)]
    with pytest.raises(ValueError):
        validate_sweep_duties(duties)


def test_build_characterization_point_preserves_signed_p_and_computes_statistics() -> None:
    point = build_characterization_point(
        session_id="TEST-1",
        mode="MANUAL_CAPTURE",
        source_id="emonio-a",
        phase="A",
        actuator_node_id="ARI-LOAD-001",
        actuator_boot_id="BOOT-1",
        command_sequence=10,
        requested_duty_percent=35.0,
        actual_duty_percent=35.068913,
        cycle_ids=(103, 104, 105),
        p_samples_w=(-7.4, -6.8, -7.1),
        utc="2026-09-02T12:00:00+00:00",
    )

    assert point.requested_duty_percent == 35.0
    assert point.actual_duty_percent == 35.068913
    assert point.cycle_ids == (103, 104, 105)
    assert point.p_samples_w == (-7.4, -6.8, -7.1)
    assert point.mean_p_w == pytest.approx(-7.1)
    assert point.min_p_w == -7.4
    assert point.max_p_w == -6.8
    assert point.sample_stdev_p_w == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("cycle_ids", "p_samples_w"),
    [
        ((1, 2), (-1.0, -2.0, -3.0)),
        ((1, 2, 3), (-1.0, -2.0)),
        ((1, 2, 3, 4), (-1.0, -2.0, -3.0)),
    ],
)
def test_build_characterization_point_requires_exactly_three_cycles_and_samples(
    cycle_ids, p_samples_w
) -> None:
    with pytest.raises(ValueError):
        build_characterization_point(
            session_id="TEST-1",
            mode="MANUAL_CAPTURE",
            source_id="emonio-a",
            phase="A",
            actuator_node_id="ARI-LOAD-001",
            actuator_boot_id="BOOT-1",
            command_sequence=10,
            requested_duty_percent=35.0,
            actual_duty_percent=35.068913,
            cycle_ids=cycle_ids,
            p_samples_w=p_samples_w,
            utc="2026-09-02T12:00:00+00:00",
        )


def test_build_characterization_point_rejects_nonfinite_p_without_sign_repair() -> None:
    with pytest.raises(ValueError):
        build_characterization_point(
            session_id="TEST-1",
            mode="MANUAL_CAPTURE",
            source_id="emonio-a",
            phase="A",
            actuator_node_id="ARI-LOAD-001",
            actuator_boot_id="BOOT-1",
            command_sequence=10,
            requested_duty_percent=35.0,
            actual_duty_percent=35.068913,
            cycle_ids=(1, 2, 3),
            p_samples_w=(-1.0, math.nan, 1.0),
            utc="2026-09-02T12:00:00+00:00",
        )


def test_build_characterization_point_allows_actual_register_duty_above_75_percent() -> None:
    point = build_characterization_point(
        session_id="TEST-1",
        mode="AUTO_SWEEP",
        source_id="emonio-a",
        phase="A",
        actuator_node_id="ARI-LOAD-001",
        actuator_boot_id="BOOT-1",
        command_sequence=11,
        requested_duty_percent=75.0,
        actual_duty_percent=75.03828484,
        cycle_ids=(1, 2, 3),
        p_samples_w=(20.0, 20.1, 19.9),
        utc="2026-09-02T12:00:00+00:00",
    )
    assert point.actual_duty_percent == 75.03828484
