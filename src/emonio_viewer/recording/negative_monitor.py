from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math

from emonio_viewer.measurement.model import MeasurementSample, SampleQuality


class NegativeCondition(str, Enum):
    P_NEGATIVE = "P_NEGATIVE"
    PF_NEGATIVE = "PF_NEGATIVE"
    P_OR_PF_NEGATIVE = "P_OR_PF_NEGATIVE"


class MonitorPhase(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MonitorMeasurement(str, Enum):
    P = "P"
    PF = "PF"


class MonitorBoundary(str, Enum):
    MONITOR_START = "MONITOR_START"
    GAP = "GAP"
    RECONNECT = "RECONNECT"


@dataclass(frozen=True, slots=True, order=True)
class ConditionKey:
    phase: MonitorPhase
    measurement: MonitorMeasurement


@dataclass(frozen=True, slots=True)
class NegativeMonitorConfig:
    device_id: str
    condition: NegativeCondition
    phases: tuple[MonitorPhase, ...]
    recording_interval_s: float

    def __post_init__(self) -> None:
        if not self.phases:
            raise ValueError("at least one monitor phase is required")
        if len(set(self.phases)) != len(self.phases):
            raise ValueError("monitor phases must be unique")
        if not math.isfinite(self.recording_interval_s):
            raise ValueError("recording interval must be finite")
        if self.recording_interval_s <= 0:
            raise ValueError("recording interval must be > 0")


@dataclass(frozen=True, slots=True)
class NegativeMonitorEvent:
    name: str
    phase: MonitorPhase
    measurement: MonitorMeasurement
    cycle_id: int
    occurred_utc: datetime
    value: float
    continuity: str


@dataclass(slots=True)
class NegativeMonitorRuntime:
    config: NegativeMonitorConfig
    enabled_utc: datetime
    enable_floor_cycle_id: int | None
    previous_cycle_id: int | None = None
    active_keys: set[ConditionKey] = field(default_factory=set)
    initialized_keys: set[ConditionKey] = field(default_factory=set)
    pending_boundary: MonitorBoundary | None = MonitorBoundary.MONITOR_START


@dataclass(frozen=True, slots=True)
class NegativeMonitorEvaluation:
    events: tuple[NegativeMonitorEvent, ...]
    active_keys: tuple[ConditionKey, ...]
    aggregate_active: bool
    first_activation: NegativeMonitorEvent | None
    all_clear_transition: bool


_PHASE_ORDER = {MonitorPhase.A: 0, MonitorPhase.B: 1, MonitorPhase.C: 2}
_MEASUREMENT_ORDER = {MonitorMeasurement.P: 0, MonitorMeasurement.PF: 1}
_PHASE_ATTR = {
    MonitorPhase.A: "phase_a",
    MonitorPhase.B: "phase_b",
    MonitorPhase.C: "phase_c",
}
_MEASUREMENT_ATTR = {
    MonitorMeasurement.P: "p",
    MonitorMeasurement.PF: "pf",
}


def _key_sort(key: ConditionKey) -> tuple[int, int]:
    return (_PHASE_ORDER[key.phase], _MEASUREMENT_ORDER[key.measurement])


def selected_condition_keys(config: NegativeMonitorConfig) -> tuple[ConditionKey, ...]:
    measurements = (
        (MonitorMeasurement.P,)
        if config.condition is NegativeCondition.P_NEGATIVE
        else (MonitorMeasurement.PF,)
        if config.condition is NegativeCondition.PF_NEGATIVE
        else (MonitorMeasurement.P, MonitorMeasurement.PF)
    )
    keys = [ConditionKey(phase, measurement) for phase in config.phases for measurement in measurements]
    return tuple(sorted(keys, key=_key_sort))


def extract_condition_value(sample: MeasurementSample, key: ConditionKey) -> float:
    block = getattr(sample, _PHASE_ATTR[key.phase])
    return getattr(block.measurement, _MEASUREMENT_ATTR[key.measurement])


def invalidate_monitor_continuity(
    runtime: NegativeMonitorRuntime,
    boundary: MonitorBoundary,
) -> None:
    runtime.pending_boundary = boundary


def _empty(runtime: NegativeMonitorRuntime) -> NegativeMonitorEvaluation:
    active = tuple(sorted(runtime.active_keys, key=_key_sort))
    return NegativeMonitorEvaluation((), active, bool(active), None, False)


def _event_name(boundary: MonitorBoundary, negative: bool) -> str | None:
    if boundary is MonitorBoundary.MONITOR_START:
        return "NEGATIVE_PRESENT_AT_MONITOR_START" if negative else None
    if boundary is MonitorBoundary.GAP:
        return "NEGATIVE_PRESENT_AFTER_GAP" if negative else "NEGATIVE_NOT_PRESENT_AFTER_GAP"
    if boundary is MonitorBoundary.RECONNECT:
        return "NEGATIVE_PRESENT_AFTER_RECONNECT" if negative else "NEGATIVE_NOT_PRESENT_AFTER_RECONNECT"
    raise ValueError(f"unsupported monitor boundary: {boundary}")


def _continuity_name(boundary: MonitorBoundary) -> str:
    if boundary is MonitorBoundary.MONITOR_START:
        return "MONITOR_START"
    if boundary is MonitorBoundary.GAP:
        return "GAP_BOUNDARY"
    if boundary is MonitorBoundary.RECONNECT:
        return "RECONNECT_BOUNDARY"
    raise ValueError(f"unsupported monitor boundary: {boundary}")


def evaluate_monitor_sample(
    runtime: NegativeMonitorRuntime,
    sample: MeasurementSample,
) -> NegativeMonitorEvaluation:
    if sample.identity.device_id != runtime.config.device_id:
        return _empty(runtime)

    cycle_id = sample.identity.cycle_id
    floor = runtime.enable_floor_cycle_id
    if floor is not None and cycle_id <= floor:
        return _empty(runtime)

    if runtime.previous_cycle_id is not None and cycle_id <= runtime.previous_cycle_id:
        return _empty(runtime)

    if sample.quality not in {SampleQuality.VALID, SampleQuality.DEGRADED}:
        invalidate_monitor_continuity(runtime, MonitorBoundary.GAP)
        return _empty(runtime)

    keys = selected_condition_keys(runtime.config)
    values = {key: extract_condition_value(sample, key) for key in keys}
    if any(not math.isfinite(value) for value in values.values()):
        invalidate_monitor_continuity(runtime, MonitorBoundary.GAP)
        return _empty(runtime)

    if (
        runtime.pending_boundary is None
        and runtime.previous_cycle_id is not None
        and cycle_id != runtime.previous_cycle_id + 1
    ):
        runtime.pending_boundary = MonitorBoundary.GAP

    before_active = bool(runtime.active_keys)
    events: list[NegativeMonitorEvent] = []
    boundary = runtime.pending_boundary

    if boundary is not None:
        continuity = _continuity_name(boundary)
        for key in keys:
            was_initialized = key in runtime.initialized_keys
            was_negative = key in runtime.active_keys
            is_negative = values[key] < 0
            name = _event_name(boundary, is_negative)
            if boundary is not MonitorBoundary.MONITOR_START:
                if not is_negative and not (was_initialized and was_negative):
                    name = None
            if is_negative:
                runtime.active_keys.add(key)
            else:
                runtime.active_keys.discard(key)
            runtime.initialized_keys.add(key)
            if name is not None:
                events.append(
                    NegativeMonitorEvent(
                        name,
                        key.phase,
                        key.measurement,
                        cycle_id,
                        sample.timing.cycle_finished_utc,
                        values[key],
                        continuity,
                    )
                )
        runtime.pending_boundary = None
    else:
        for key in keys:
            is_negative = values[key] < 0
            was_negative = key in runtime.active_keys
            if key not in runtime.initialized_keys:
                runtime.initialized_keys.add(key)
                if is_negative:
                    runtime.active_keys.add(key)
                    events.append(
                        NegativeMonitorEvent(
                            "NEGATIVE_PRESENT_AT_MONITOR_START",
                            key.phase,
                            key.measurement,
                            cycle_id,
                            sample.timing.cycle_finished_utc,
                            values[key],
                            "MONITOR_START",
                        )
                    )
                continue
            if not was_negative and is_negative:
                runtime.active_keys.add(key)
                events.append(
                    NegativeMonitorEvent(
                        "NEGATIVE_START",
                        key.phase,
                        key.measurement,
                        cycle_id,
                        sample.timing.cycle_finished_utc,
                        values[key],
                        "EXACT",
                    )
                )
            elif was_negative and not is_negative:
                runtime.active_keys.discard(key)
                events.append(
                    NegativeMonitorEvent(
                        "NEGATIVE_END",
                        key.phase,
                        key.measurement,
                        cycle_id,
                        sample.timing.cycle_finished_utc,
                        values[key],
                        "EXACT",
                    )
                )

    runtime.previous_cycle_id = cycle_id
    active = tuple(sorted(runtime.active_keys, key=_key_sort))
    aggregate_active = bool(active)
    first_activation = None
    if not before_active and aggregate_active:
        for event in events:
            if event.name in {
                "NEGATIVE_START",
                "NEGATIVE_PRESENT_AT_MONITOR_START",
                "NEGATIVE_PRESENT_AFTER_GAP",
                "NEGATIVE_PRESENT_AFTER_RECONNECT",
            }:
                first_activation = event
                break
    return NegativeMonitorEvaluation(
        tuple(events),
        active,
        aggregate_active,
        first_activation,
        before_active and not aggregate_active,
    )
