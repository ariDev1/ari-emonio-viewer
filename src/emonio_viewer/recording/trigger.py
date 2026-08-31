from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

from emonio_viewer.measurement.model import MeasurementSample, SampleQuality


class TriggerMode(str, Enum):
    LEVEL = "LEVEL"
    CROSSING = "CROSSING"


class TriggerBlock(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    TOTAL = "TOTAL"


class TriggerMeasurement(str, Enum):
    U = "U"
    I = "I"
    P = "P"
    Q = "Q"
    S = "S"
    PF = "PF"
    F = "F"


class TriggerOperator(str, Enum):
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"


@dataclass(frozen=True, slots=True)
class TriggerConfig:
    device_id: str
    block: TriggerBlock
    measurement: TriggerMeasurement
    operator: TriggerOperator
    threshold: float
    mode: TriggerMode
    recording_interval_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold):
            raise ValueError("trigger threshold must be finite")
        if not math.isfinite(self.recording_interval_s):
            raise ValueError("recording interval must be finite")
        if self.recording_interval_s <= 0:
            raise ValueError("recording interval must be > 0")


@dataclass(slots=True)
class TriggerRuntimeState:
    config: TriggerConfig
    armed_utc: datetime
    arm_floor_cycle_id: int | None
    previous_cycle_id: int | None = None
    previous_value: float | None = None
    previous_sample_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class TriggerFire:
    cycle_id: int
    fired_utc: datetime
    value: float


_BLOCK_ATTR = {
    TriggerBlock.A: "phase_a",
    TriggerBlock.B: "phase_b",
    TriggerBlock.C: "phase_c",
    TriggerBlock.TOTAL: "total",
}

_MEASUREMENT_ATTR = {
    TriggerMeasurement.U: "vrms",
    TriggerMeasurement.I: "irms",
    TriggerMeasurement.P: "p",
    TriggerMeasurement.Q: "q",
    TriggerMeasurement.S: "s",
    TriggerMeasurement.PF: "pf",
    TriggerMeasurement.F: "frequency",
}


def extract_trigger_value(sample: MeasurementSample, config: TriggerConfig) -> float:
    block = getattr(sample, _BLOCK_ATTR[config.block])
    return getattr(block.measurement, _MEASUREMENT_ATTR[config.measurement])


def invalidate_crossing_continuity(state: TriggerRuntimeState) -> None:
    state.previous_cycle_id = None
    state.previous_value = None
    state.previous_sample_utc = None


def _matches(operator: TriggerOperator, value: float, threshold: float) -> bool:
    if operator is TriggerOperator.GT:
        return value > threshold
    if operator is TriggerOperator.GE:
        return value >= threshold
    if operator is TriggerOperator.LT:
        return value < threshold
    return value <= threshold


def _crosses(operator: TriggerOperator, previous: float, current: float, threshold: float) -> bool:
    if operator is TriggerOperator.GT:
        return previous <= threshold and current > threshold
    if operator is TriggerOperator.GE:
        return previous < threshold and current >= threshold
    if operator is TriggerOperator.LT:
        return previous >= threshold and current < threshold
    return previous > threshold and current <= threshold


def evaluate_measurement(
    state: TriggerRuntimeState,
    sample: MeasurementSample,
) -> TriggerFire | None:
    if sample.identity.device_id != state.config.device_id:
        return None
    if sample.quality not in {SampleQuality.VALID, SampleQuality.DEGRADED}:
        if state.config.mode is TriggerMode.CROSSING:
            invalidate_crossing_continuity(state)
        return None

    cycle_id = sample.identity.cycle_id
    if state.arm_floor_cycle_id is not None and cycle_id <= state.arm_floor_cycle_id:
        return None

    value = extract_trigger_value(sample, state.config)
    if not math.isfinite(value):
        if state.config.mode is TriggerMode.CROSSING:
            invalidate_crossing_continuity(state)
        return None

    if state.config.mode is TriggerMode.LEVEL:
        if _matches(state.config.operator, value, state.config.threshold):
            return TriggerFire(cycle_id, sample.timing.cycle_finished_utc, value)
        return None

    if state.previous_cycle_id is None:
        state.previous_cycle_id = cycle_id
        state.previous_value = value
        state.previous_sample_utc = sample.timing.cycle_finished_utc
        return None

    if cycle_id <= state.previous_cycle_id:
        return None

    previous_cycle_id = state.previous_cycle_id
    previous_value = state.previous_value
    if cycle_id != previous_cycle_id + 1:
        state.previous_cycle_id = cycle_id
        state.previous_value = value
        state.previous_sample_utc = sample.timing.cycle_finished_utc
        return None

    state.previous_cycle_id = cycle_id
    state.previous_value = value
    state.previous_sample_utc = sample.timing.cycle_finished_utc
    if previous_value is not None and _crosses(
        state.config.operator,
        previous_value,
        value,
        state.config.threshold,
    ):
        return TriggerFire(cycle_id, sample.timing.cycle_finished_utc, value)
    return None
