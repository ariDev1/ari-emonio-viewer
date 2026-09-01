from datetime import datetime, timezone
import math

import pytest

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.measurement.model import (
    AcquisitionMetadata,
    BlockState,
    DerivedTotals,
    MeasurementIdentity,
    MeasurementSample,
    PhaseMeasurement,
    RawBlockEvidence,
    SampleQuality,
    SampleTiming,
)
from emonio_viewer.measurement.quadrant import ActiveFlowState, QuadrantState
import emonio_viewer.recording.negative_monitor as monitor
from emonio_viewer.recording.recorder import RecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus


def sample(*, cycle=1, a_q=0.0, b_q=0.0, c_q=0.0):
    observed_utc = datetime(2026, 9, 1, 6, 0, cycle % 60, tzinfo=timezone.utc)

    def block(q):
        p = 1.0
        measurement = PhaseMeasurement(
            230.0,
            1.0,
            p,
            q,
            math.hypot(p, q),
            50.0,
            0.0,
            1.0,
        )
        return BlockState(
            measurement,
            QuadrantState.Q1,
            ActiveFlowState.POSITIVE_FLOW,
            observed_utc,
            RawBlockEvidence(0, ()),
        )

    return MeasurementSample(
        MeasurementIdentity(
            1,
            "emonio-a",
            "emonio-a",
            "192.0.2.1",
            "3.0.79",
            "MODBUS_TCP",
            cycle,
        ),
        SampleTiming(observed_utc, observed_utc, 1, 2, 1.0),
        AcquisitionMetadata(0.0),
        block(a_q),
        block(b_q),
        block(c_q),
        block(a_q + b_q + c_q),
        SampleQuality.VALID,
        (),
        DerivedTotals(0, 0, 0, 0, 0, 0),
    )


def q_config(direction="POSITIVE", threshold=100.0, phases=None):
    assert hasattr(monitor.NegativeCondition, "Q_THRESHOLD")
    assert hasattr(monitor.MonitorMeasurement, "Q")
    assert hasattr(monitor, "QDirection")
    selected_phases = phases or (monitor.MonitorPhase.A,)
    return monitor.NegativeMonitorConfig(
        device_id="emonio-a",
        condition=monitor.NegativeCondition.Q_THRESHOLD,
        phases=selected_phases,
        recording_interval_s=2.0,
        threshold_var=threshold,
        q_direction=monitor.QDirection(direction),
    )


def runtime(config):
    return monitor.NegativeMonitorRuntime(
        config,
        datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc),
        0,
    )


def test_q_threshold_condition_types_are_explicit():
    assert hasattr(monitor.NegativeCondition, "Q_THRESHOLD")
    assert hasattr(monitor.MonitorMeasurement, "Q")
    assert hasattr(monitor, "QDirection")
    assert tuple(item.value for item in monitor.QDirection) == (
        "POSITIVE",
        "NEGATIVE",
        "BOTH",
    )


def test_q_threshold_selects_exact_q_field_for_each_selected_phase():
    config = q_config(
        "BOTH",
        100.0,
        (monitor.MonitorPhase.C, monitor.MonitorPhase.A),
    )
    assert monitor.selected_condition_keys(config) == (
        monitor.ConditionKey(monitor.MonitorPhase.A, monitor.MonitorMeasurement.Q),
        monitor.ConditionKey(monitor.MonitorPhase.C, monitor.MonitorMeasurement.Q),
    )
    observed = sample(b_q=-123.456789)
    key = monitor.ConditionKey(monitor.MonitorPhase.B, monitor.MonitorMeasurement.Q)
    assert monitor.extract_condition_value(observed, key) == -123.456789


def test_positive_q_threshold_is_strict_and_clears_when_direction_is_not_active():
    state = runtime(q_config("POSITIVE", 100.0))
    at_threshold = monitor.evaluate_monitor_sample(state, sample(cycle=1, a_q=100.0))
    assert at_threshold.events == ()
    assert at_threshold.aggregate_active is False

    start = monitor.evaluate_monitor_sample(state, sample(cycle=2, a_q=100.0001))
    assert [event.name for event in start.events] == ["Q_THRESHOLD_START"]
    assert start.events[0].value == 100.0001
    assert start.aggregate_active is True

    end = monitor.evaluate_monitor_sample(state, sample(cycle=3, a_q=-500.0))
    assert [event.name for event in end.events] == ["Q_THRESHOLD_END"]
    assert end.aggregate_active is False
    assert end.all_clear_transition is True


def test_negative_q_threshold_is_strict():
    state = runtime(q_config("NEGATIVE", 100.0))
    at_threshold = monitor.evaluate_monitor_sample(state, sample(cycle=1, a_q=-100.0))
    assert at_threshold.events == ()
    assert at_threshold.aggregate_active is False

    start = monitor.evaluate_monitor_sample(state, sample(cycle=2, a_q=-100.0001))
    assert [event.name for event in start.events] == ["Q_THRESHOLD_START"]
    assert start.events[0].value == -100.0001
    assert start.aggregate_active is True

    end = monitor.evaluate_monitor_sample(state, sample(cycle=3, a_q=500.0))
    assert [event.name for event in end.events] == ["Q_THRESHOLD_END"]
    assert end.aggregate_active is False


def test_both_q_threshold_accepts_either_sign_without_false_clear_between_signs():
    state = runtime(q_config("BOTH", 100.0))
    monitor.evaluate_monitor_sample(state, sample(cycle=1, a_q=0.0))

    positive = monitor.evaluate_monitor_sample(state, sample(cycle=2, a_q=101.0))
    assert [event.name for event in positive.events] == ["Q_THRESHOLD_START"]
    assert positive.aggregate_active is True

    negative = monitor.evaluate_monitor_sample(state, sample(cycle=3, a_q=-101.0))
    assert negative.events == ()
    assert negative.aggregate_active is True

    at_threshold = monitor.evaluate_monitor_sample(state, sample(cycle=4, a_q=-100.0))
    assert [event.name for event in at_threshold.events] == ["Q_THRESHOLD_END"]
    assert at_threshold.aggregate_active is False


def test_q_threshold_gap_uses_bounded_presence_evidence_not_crossing_claim():
    state = runtime(q_config("POSITIVE", 100.0))
    monitor.evaluate_monitor_sample(state, sample(cycle=1, a_q=0.0))
    result = monitor.evaluate_monitor_sample(state, sample(cycle=3, a_q=101.0))
    assert [event.name for event in result.events] == ["Q_THRESHOLD_PRESENT_AFTER_GAP"]
    assert result.events[0].continuity == "GAP_BOUNDARY"
    assert result.first_activation == result.events[0]


@pytest.mark.parametrize("threshold", (-1.0, float("nan"), float("inf"), float("-inf")))
def test_q_threshold_rejects_invalid_threshold_magnitude(threshold):
    with pytest.raises(ValueError, match="threshold"):
        q_config("BOTH", threshold)


def test_q_threshold_requires_direction():
    assert hasattr(monitor.NegativeCondition, "Q_THRESHOLD")
    with pytest.raises(ValueError, match="direction"):
        monitor.NegativeMonitorConfig(
            device_id="emonio-a",
            condition=monitor.NegativeCondition.Q_THRESHOLD,
            phases=(monitor.MonitorPhase.A,),
            recording_interval_s=2.0,
            threshold_var=100.0,
            q_direction=None,
        )


class FakeStore:
    def get_device(self, _device_id):
        return type("Snapshot", (), {"last_sample": None})()


def test_q_monitor_status_exposes_threshold_and_direction(tmp_path):
    device = DeviceConfig("emonio-a", "EMONIO A", "192.0.2.1")
    manager = RecordingManager(
        tmp_path,
        (device,),
        FakeStore(),
        RuntimeEventBus(),
        "0.4.19",
    )
    status = manager.configure_monitor(q_config("NEGATIVE", 250.0))
    assert status["config"] == {
        "condition": "Q_THRESHOLD",
        "phases": ["A"],
        "recording_interval_s": 2.0,
        "threshold_var": 250.0,
        "q_direction": "NEGATIVE",
    }
