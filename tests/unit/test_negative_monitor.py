from datetime import datetime, timezone

import pytest

from emonio_viewer.measurement.model import (
    AcquisitionMetadata, BlockState, DerivedTotals, MeasurementIdentity, MeasurementSample,
    PhaseMeasurement, RawBlockEvidence, SampleQuality, SampleTiming,
)
from emonio_viewer.measurement.quadrant import ActiveFlowState, QuadrantState
from emonio_viewer.recording.negative_monitor import (
    ConditionKey, MonitorBoundary, MonitorMeasurement, MonitorPhase, NegativeCondition,
    NegativeMonitorConfig, NegativeMonitorRuntime, evaluate_monitor_sample,
    extract_condition_value, invalidate_monitor_continuity, selected_condition_keys,
)


def sample(*, cycle=1, device="emonio-a", quality=SampleQuality.VALID,
           a_p=1.0, a_pf=1.0, b_p=1.0, b_pf=1.0, c_p=1.0, c_pf=1.0):
    t = datetime(2026, 8, 31, 8, 0, cycle % 60, tzinfo=timezone.utc)
    def block(p, pf):
        m = PhaseMeasurement(230.0, 1.0, p, 0.0, abs(p), 50.0, 0.0, pf)
        return BlockState(m, QuadrantState.Q1, ActiveFlowState.POSITIVE_FLOW, t, RawBlockEvidence(0, ()))
    return MeasurementSample(
        MeasurementIdentity(1, device, device, "192.0.2.1", "3.0.79", "MODBUS_TCP", cycle),
        SampleTiming(t, t, 1, 2, 1.0), AcquisitionMetadata(0.0),
        block(a_p, a_pf), block(b_p, b_pf), block(c_p, c_pf), block(a_p+b_p+c_p, 1.0),
        quality, (), DerivedTotals(0,0,0,0,0,0),
    )


def cfg(condition=NegativeCondition.P_NEGATIVE, phases=(MonitorPhase.A,), interval=2.0):
    return NegativeMonitorConfig("emonio-a", condition, phases, interval)


def runtime(config=None, floor=None):
    return NegativeMonitorRuntime(
        config or cfg(),
        datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc),
        floor,
    )


def test_p_negative_selects_p_for_each_selected_phase():
    assert selected_condition_keys(cfg(phases=(MonitorPhase.A, MonitorPhase.C))) == (
        ConditionKey(MonitorPhase.A, MonitorMeasurement.P),
        ConditionKey(MonitorPhase.C, MonitorMeasurement.P),
    )


def test_pf_negative_selects_pf_only():
    assert selected_condition_keys(cfg(NegativeCondition.PF_NEGATIVE, (MonitorPhase.B,))) == (
        ConditionKey(MonitorPhase.B, MonitorMeasurement.PF),
    )


def test_p_or_pf_uses_deterministic_phase_then_measurement_order():
    assert selected_condition_keys(cfg(NegativeCondition.P_OR_PF_NEGATIVE, (MonitorPhase.C, MonitorPhase.A))) == (
        ConditionKey(MonitorPhase.A, MonitorMeasurement.P),
        ConditionKey(MonitorPhase.A, MonitorMeasurement.PF),
        ConditionKey(MonitorPhase.C, MonitorMeasurement.P),
        ConditionKey(MonitorPhase.C, MonitorMeasurement.PF),
    )


def test_config_rejects_empty_duplicate_phases_and_invalid_interval():
    with pytest.raises(ValueError, match="at least one monitor phase is required"):
        cfg(phases=())
    with pytest.raises(ValueError, match="monitor phases must be unique"):
        cfg(phases=(MonitorPhase.A, MonitorPhase.A))
    for value in (0.0, -1.0):
        with pytest.raises(ValueError, match="recording interval must be > 0"):
            cfg(interval=value)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="recording interval must be finite"):
            cfg(interval=value)


def test_extract_condition_value_uses_exact_phase_field():
    s = sample(b_p=-12.3456789, b_pf=-0.87654321)
    assert extract_condition_value(s, ConditionKey(MonitorPhase.B, MonitorMeasurement.P)) == -12.3456789
    assert extract_condition_value(s, ConditionKey(MonitorPhase.B, MonitorMeasurement.PF)) == -0.87654321


@pytest.mark.parametrize(("previous","current","event"), [
    (1.0, -1.0, "NEGATIVE_START"),
    (0.0, -1.0, "NEGATIVE_START"),
    (-1.0, 0.0, "NEGATIVE_END"),
    (-1.0, 1.0, "NEGATIVE_END"),
])
def test_exact_transition_truth_table(previous, current, event):
    r = runtime(floor=0)
    first = evaluate_monitor_sample(r, sample(cycle=1, a_p=previous))
    if previous < 0:
        assert [item.name for item in first.events] == ["NEGATIVE_PRESENT_AT_MONITOR_START"]
    else:
        assert first.events == ()
    result = evaluate_monitor_sample(r, sample(cycle=2, a_p=current))
    assert [item.name for item in result.events] == [event]
    item = result.events[0]
    assert item.cycle_id == 2
    assert item.occurred_utc == sample(cycle=2).timing.cycle_finished_utc
    assert item.value == current
    assert item.continuity == "EXACT"


def test_same_sign_exact_samples_create_no_event():
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1.0))
    assert evaluate_monitor_sample(r, sample(cycle=2, a_p=2.0)).events == ()
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=-1.0))
    assert evaluate_monitor_sample(r, sample(cycle=2, a_p=-2.0)).events == ()


def test_first_post_enable_negative_is_presence_not_crossing_and_is_first_activation():
    r = runtime(floor=10)
    assert evaluate_monitor_sample(r, sample(cycle=10, a_p=-5.0)).events == ()
    result = evaluate_monitor_sample(r, sample(cycle=11, a_p=-5.0))
    assert [e.name for e in result.events] == ["NEGATIVE_PRESENT_AT_MONITOR_START"]
    assert result.events[0].continuity == "MONITOR_START"
    assert result.first_activation == result.events[0]
    assert result.aggregate_active is True


def test_first_sample_multiple_negative_keys_use_deterministic_order():
    r = runtime(cfg(NegativeCondition.P_OR_PF_NEGATIVE, (MonitorPhase.C, MonitorPhase.A)), floor=0)
    result = evaluate_monitor_sample(r, sample(cycle=1, a_p=-1, a_pf=-0.5, c_p=-2, c_pf=-0.7))
    assert [(e.phase.value, e.measurement.value) for e in result.events] == [
        ("A", "P"), ("A", "PF"), ("C", "P"), ("C", "PF")
    ]
    assert result.first_activation == result.events[0]


def test_other_device_pre_enable_duplicate_and_stale_do_not_change_runtime():
    r = runtime(floor=10)
    evaluate_monitor_sample(r, sample(cycle=10, a_p=-1))
    evaluate_monitor_sample(r, sample(cycle=11, device="emonio-b", a_p=-1))
    assert r.previous_cycle_id is None
    evaluate_monitor_sample(r, sample(cycle=11, a_p=1))
    before = (r.previous_cycle_id, set(r.active_keys), set(r.initialized_keys))
    evaluate_monitor_sample(r, sample(cycle=11, a_p=-1))
    evaluate_monitor_sample(r, sample(cycle=9, a_p=-1))
    assert (r.previous_cycle_id, set(r.active_keys), set(r.initialized_keys)) == before


def test_cycle_gap_creates_gap_boundary_and_does_not_claim_crossing():
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1))
    result = evaluate_monitor_sample(r, sample(cycle=3, a_p=-2))
    assert [e.name for e in result.events] == ["NEGATIVE_PRESENT_AFTER_GAP"]
    assert result.events[0].continuity == "GAP_BOUNDARY"


def test_gap_from_negative_to_nonnegative_is_bounded_end():
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=-1))
    invalidate_monitor_continuity(r, MonitorBoundary.GAP)
    result = evaluate_monitor_sample(r, sample(cycle=2, a_p=1))
    assert [e.name for e in result.events] == ["NEGATIVE_NOT_PRESENT_AFTER_GAP"]
    assert result.all_clear_transition is True


def test_reconnect_boundary_uses_reconnect_event_even_with_consecutive_cycle():
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1))
    invalidate_monitor_continuity(r, MonitorBoundary.RECONNECT)
    result = evaluate_monitor_sample(r, sample(cycle=2, a_p=-1))
    assert [e.name for e in result.events] == ["NEGATIVE_PRESENT_AFTER_RECONNECT"]
    assert result.events[0].continuity == "RECONNECT_BOUNDARY"


def test_invalid_quality_breaks_continuity():
    r = runtime(floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1))
    assert evaluate_monitor_sample(r, sample(cycle=2, quality=SampleQuality.INVALID, a_p=-1)).events == ()
    result = evaluate_monitor_sample(r, sample(cycle=3, a_p=-1))
    assert [e.name for e in result.events] == ["NEGATIVE_PRESENT_AFTER_GAP"]


def test_non_finite_selected_value_breaks_all_selected_sample_continuity():
    r = runtime(cfg(NegativeCondition.P_OR_PF_NEGATIVE, (MonitorPhase.A,)), floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1, a_pf=1))
    assert evaluate_monitor_sample(r, sample(cycle=2, a_p=-1, a_pf=float("nan"))).events == ()
    result = evaluate_monitor_sample(r, sample(cycle=3, a_p=-1, a_pf=1))
    assert [e.name for e in result.events] == ["NEGATIVE_PRESENT_AFTER_GAP"]


def test_p_or_pf_activity_remains_active_until_both_are_nonnegative():
    r = runtime(cfg(NegativeCondition.P_OR_PF_NEGATIVE, (MonitorPhase.A,)), floor=0)
    evaluate_monitor_sample(r, sample(cycle=1, a_p=1, a_pf=1))
    start_p = evaluate_monitor_sample(r, sample(cycle=2, a_p=-1, a_pf=1))
    assert start_p.aggregate_active is True
    start_pf = evaluate_monitor_sample(r, sample(cycle=3, a_p=-1, a_pf=-0.5))
    assert [e.name for e in start_pf.events] == ["NEGATIVE_START"]
    end_p = evaluate_monitor_sample(r, sample(cycle=4, a_p=1, a_pf=-0.5))
    assert [e.name for e in end_p.events] == ["NEGATIVE_END"]
    assert end_p.aggregate_active is True
    end_pf = evaluate_monitor_sample(r, sample(cycle=5, a_p=1, a_pf=0))
    assert [e.name for e in end_pf.events] == ["NEGATIVE_END"]
    assert end_pf.aggregate_active is False
    assert end_pf.all_clear_transition is True
