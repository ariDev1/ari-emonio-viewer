from dataclasses import replace
from datetime import datetime, timezone

import pytest

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
from emonio_viewer.recording.trigger import (
    TriggerBlock,
    TriggerConfig,
    TriggerMeasurement,
    TriggerMode,
    TriggerOperator,
    TriggerRuntimeState,
    evaluate_measurement,
    extract_trigger_value,
    invalidate_crossing_continuity,
)


def make_sample(
    *,
    cycle_id: int = 10,
    device_id: str = "emonio-a",
    quality: SampleQuality = SampleQuality.VALID,
    p: float = 10.0,
) -> MeasurementSample:
    now = datetime(2026, 8, 31, 6, 0, cycle_id % 60, tzinfo=timezone.utc)
    measurement = PhaseMeasurement(
        vrms=230.1,
        irms=5.2,
        p=p,
        q=-120.5,
        s=1250.25,
        frequency=50.01,
        energy=-1.25,
        pf=0.8123456789,
    )
    block = BlockState(
        measurement=measurement,
        quadrant=QuadrantState.Q4,
        flow=ActiveFlowState.POSITIVE_FLOW,
        acquired_utc=now,
        raw=RawBlockEvidence(base_register=0, words=()),
    )
    return MeasurementSample(
        identity=MeasurementIdentity(
            schema_version=1,
            device_id=device_id,
            device_name=device_id,
            device_ip="192.0.2.1",
            firmware_version="3.0.79",
            transport="MODBUS_TCP",
            cycle_id=cycle_id,
        ),
        timing=SampleTiming(
            cycle_started_utc=now,
            cycle_finished_utc=now,
            cycle_started_monotonic_ns=1,
            cycle_finished_monotonic_ns=2,
            cycle_span_ms=1.0,
        ),
        acquisition=AcquisitionMetadata(schedule_lag_ms=0.0),
        phase_a=block,
        phase_b=block,
        phase_c=block,
        total=block,
        quality=quality,
        warnings=(),
        derived=DerivedTotals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def with_block_value(sample, block_name: str, field: str, value: float):
    block = getattr(sample, block_name)
    measurement = replace(block.measurement, **{field: value})
    return replace(sample, **{block_name: replace(block, measurement=measurement)})


def config(
    *,
    block=TriggerBlock.A,
    measurement=TriggerMeasurement.P,
    operator=TriggerOperator.GT,
    threshold=0.0,
    mode=TriggerMode.LEVEL,
    device_id="emonio-a",
):
    return TriggerConfig(
        device_id=device_id,
        block=block,
        measurement=measurement,
        operator=operator,
        threshold=threshold,
        mode=mode,
        recording_interval_s=1.0,
    )


def armed(cfg: TriggerConfig, floor: int | None = None):
    return TriggerRuntimeState(
        config=cfg,
        armed_utc=datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc),
        arm_floor_cycle_id=floor,
    )


@pytest.mark.parametrize(
    ("measurement", "field"),
    [
        (TriggerMeasurement.U, "vrms"),
        (TriggerMeasurement.I, "irms"),
        (TriggerMeasurement.P, "p"),
        (TriggerMeasurement.Q, "q"),
        (TriggerMeasurement.S, "s"),
        (TriggerMeasurement.PF, "pf"),
        (TriggerMeasurement.F, "frequency"),
    ],
)
def test_extract_trigger_value_uses_exact_canonical_field(measurement, field):
    sample = make_sample()
    expected = getattr(sample.phase_b.measurement, field)
    assert extract_trigger_value(
        sample,
        config(block=TriggerBlock.B, measurement=measurement),
    ) == expected


@pytest.mark.parametrize(
    ("block", "attribute"),
    [
        (TriggerBlock.A, "phase_a"),
        (TriggerBlock.B, "phase_b"),
        (TriggerBlock.C, "phase_c"),
        (TriggerBlock.TOTAL, "total"),
    ],
)
def test_extract_trigger_value_uses_selected_block(block, attribute):
    sample = with_block_value(make_sample(), attribute, "p", 123.456)
    assert extract_trigger_value(sample, config(block=block)) == 123.456


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_trigger_config_rejects_non_finite_threshold(value):
    with pytest.raises(ValueError, match="threshold must be finite"):
        config(threshold=value)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_trigger_config_rejects_invalid_recording_interval(value):
    kwargs = dict(
        device_id="emonio-a",
        block=TriggerBlock.A,
        measurement=TriggerMeasurement.P,
        operator=TriggerOperator.GT,
        threshold=0.0,
        mode=TriggerMode.LEVEL,
        recording_interval_s=value,
    )
    with pytest.raises(ValueError, match="recording interval"):
        TriggerConfig(**kwargs)


@pytest.mark.parametrize(
    ("operator", "value", "fires"),
    [
        (TriggerOperator.GT, 10.0, False),
        (TriggerOperator.GT, 10.1, True),
        (TriggerOperator.GE, 10.0, True),
        (TriggerOperator.GE, 9.9, False),
        (TriggerOperator.LT, 10.0, False),
        (TriggerOperator.LT, 9.9, True),
        (TriggerOperator.LE, 10.0, True),
        (TriggerOperator.LE, 10.1, False),
    ],
)
def test_level_operator_semantics(operator, value, fires):
    sample = with_block_value(make_sample(cycle_id=11), "phase_a", "p", value)
    fire = evaluate_measurement(
        armed(config(operator=operator, threshold=10.0, mode=TriggerMode.LEVEL), floor=10),
        sample,
    )
    assert (fire is not None) is fires
    if fire is not None:
        assert fire.cycle_id == sample.identity.cycle_id
        assert fire.fired_utc == sample.timing.cycle_finished_utc
        assert fire.value == value


def test_level_ignores_pre_arm_stale_other_device_and_non_finite_values():
    state = armed(config(threshold=0.0), floor=10)
    assert evaluate_measurement(state, make_sample(cycle_id=10, p=100.0)) is None
    assert evaluate_measurement(state, make_sample(cycle_id=11, device_id="emonio-b", p=100.0)) is None
    stale = replace(make_sample(cycle_id=11, p=100.0), quality=SampleQuality.STALE)
    assert evaluate_measurement(state, stale) is None
    non_finite = with_block_value(make_sample(cycle_id=11), "phase_a", "p", float("nan"))
    assert evaluate_measurement(state, non_finite) is None


@pytest.mark.parametrize(
    ("operator", "previous", "current", "fires"),
    [
        (TriggerOperator.GT, 10.0, 10.1, True),
        (TriggerOperator.GT, 9.9, 10.0, False),
        (TriggerOperator.GE, 9.9, 10.0, True),
        (TriggerOperator.GE, 10.0, 10.1, False),
        (TriggerOperator.LT, 10.0, 9.9, True),
        (TriggerOperator.LT, 10.1, 10.0, False),
        (TriggerOperator.LE, 10.1, 10.0, True),
        (TriggerOperator.LE, 10.0, 9.9, False),
    ],
)
def test_crossing_operator_semantics(operator, previous, current, fires):
    state = armed(config(operator=operator, threshold=10.0, mode=TriggerMode.CROSSING), floor=10)
    first = with_block_value(make_sample(cycle_id=11), "phase_a", "p", previous)
    second = with_block_value(make_sample(cycle_id=12), "phase_a", "p", current)
    assert evaluate_measurement(state, first) is None
    fire = evaluate_measurement(state, second)
    assert (fire is not None) is fires


def test_crossing_requires_consecutive_cycles_and_rebases_after_gap():
    state = armed(config(threshold=10.0, mode=TriggerMode.CROSSING), floor=10)
    assert evaluate_measurement(state, make_sample(cycle_id=11, p=9.0)) is None
    assert evaluate_measurement(state, make_sample(cycle_id=13, p=11.0)) is None
    assert state.previous_cycle_id == 13
    assert state.previous_value == 11.0
    assert evaluate_measurement(state, make_sample(cycle_id=14, p=12.0)) is None


def test_crossing_ignores_duplicate_and_stale_cycles_without_replacing_baseline():
    state = armed(config(threshold=10.0, mode=TriggerMode.CROSSING), floor=10)
    assert evaluate_measurement(state, make_sample(cycle_id=11, p=9.0)) is None
    assert evaluate_measurement(state, make_sample(cycle_id=11, p=11.0)) is None
    assert evaluate_measurement(state, make_sample(cycle_id=9, p=11.0)) is None
    assert state.previous_cycle_id == 11
    assert state.previous_value == 9.0
    fire = evaluate_measurement(state, make_sample(cycle_id=12, p=11.0))
    assert fire is not None


def test_crossing_continuity_invalidation_clears_previous_evidence():
    state = armed(config(threshold=10.0, mode=TriggerMode.CROSSING), floor=10)
    first = make_sample(cycle_id=11, p=9.0)
    assert evaluate_measurement(state, first) is None
    invalidate_crossing_continuity(state)
    assert state.previous_cycle_id is None
    assert state.previous_value is None
    assert state.previous_sample_utc is None
    assert evaluate_measurement(state, make_sample(cycle_id=12, p=11.0)) is None


def test_other_device_sample_does_not_change_crossing_state():
    state = armed(config(threshold=10.0, mode=TriggerMode.CROSSING), floor=10)
    assert evaluate_measurement(state, make_sample(cycle_id=11, p=9.0)) is None
    before = (state.previous_cycle_id, state.previous_value, state.previous_sample_utc)
    assert evaluate_measurement(state, make_sample(cycle_id=12, device_id="emonio-b", p=11.0)) is None
    assert (state.previous_cycle_id, state.previous_value, state.previous_sample_utc) == before
