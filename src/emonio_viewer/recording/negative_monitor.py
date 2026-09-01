from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math

from emonio_viewer.measurement.model import MeasurementSample, SampleQuality


class NegativeCondition(str, Enum):
    P_NEGATIVE = "P_NEGATIVE"
    Q_THRESHOLD = "Q_THRESHOLD"


class QDirection(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    BOTH = "BOTH"


class MonitorPhase(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MonitorMeasurement(str, Enum):
    P = "P"
    Q = "Q"


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
    threshold_var: float | None = None
    q_direction: QDirection | None = None

    def __post_init__(self) -> None:
        if not self.phases:
            raise ValueError("at least one monitor phase is required")
        if len(set(self.phases)) != len(self.phases):
            raise ValueError("monitor phases must be unique")
        if not math.isfinite(self.recording_interval_s):
            raise ValueError("recording interval must be finite")
        if self.recording_interval_s <= 0:
            raise ValueError("recording interval must be > 0")

        if self.condition is NegativeCondition.Q_THRESHOLD:
            threshold = self.threshold_var
            if (
                threshold is None
                or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
            ):
                raise ValueError("Q threshold must be a finite non-negative magnitude")
            if not math.isfinite(threshold):
                raise ValueError("Q threshold must be finite")
            if threshold < 0:
                raise ValueError("Q threshold must be >= 0")
            if not isinstance(self.q_direction, QDirection):
                raise ValueError("Q direction is required for Q threshold monitoring")


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
_MEASUREMENT_ORDER = {MonitorMeasurement.P: 0, MonitorMeasurement.Q: 1}
_PHASE_ATTR = {
    MonitorPhase.A: "phase_a",
    MonitorPhase.B: "phase_b",
    MonitorPhase.C: "phase_c",
}
_MEASUREMENT_ATTR = {MonitorMeasurement.P: "p", MonitorMeasurement.Q: "q"}


def _key_sort(key: ConditionKey) -> tuple[int, int]:
    return (_PHASE_ORDER[key.phase], _MEASUREMENT_ORDER[key.measurement])


def selected_condition_keys(config: NegativeMonitorConfig) -> tuple[ConditionKey, ...]:
    if config.condition is NegativeCondition.P_NEGATIVE:
        measurement = MonitorMeasurement.P
    elif config.condition is NegativeCondition.Q_THRESHOLD:
        measurement = MonitorMeasurement.Q
    else:
        raise ValueError(f"unsupported monitor condition: {config.condition}")
    keys = [ConditionKey(phase, measurement) for phase in config.phases]
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


def _condition_active(config: NegativeMonitorConfig, value: float) -> bool:
    if config.condition is NegativeCondition.P_NEGATIVE:
        return value < 0

    if config.condition is NegativeCondition.Q_THRESHOLD:
        threshold = config.threshold_var
        direction = config.q_direction
        if threshold is None or direction is None:
            raise RuntimeError("Q threshold monitor configuration is incomplete")
        if direction is QDirection.POSITIVE:
            return value > threshold
        if direction is QDirection.NEGATIVE:
            return value < -threshold
        if direction is QDirection.BOTH:
            return value > threshold or value < -threshold
        raise ValueError(f"unsupported Q direction: {direction}")

    raise ValueError(f"unsupported monitor condition: {config.condition}")


def _boundary_event_name(
    config: NegativeMonitorConfig,
    boundary: MonitorBoundary,
    active: bool,
) -> str | None:
    if config.condition is NegativeCondition.P_NEGATIVE:
        if boundary is MonitorBoundary.MONITOR_START:
            return "NEGATIVE_PRESENT_AT_MONITOR_START" if active else None
        if boundary is MonitorBoundary.GAP:
            return "NEGATIVE_PRESENT_AFTER_GAP" if active else "NEGATIVE_NOT_PRESENT_AFTER_GAP"
        if boundary is MonitorBoundary.RECONNECT:
            return "NEGATIVE_PRESENT_AFTER_RECONNECT" if active else "NEGATIVE_NOT_PRESENT_AFTER_RECONNECT"
    elif config.condition is NegativeCondition.Q_THRESHOLD:
        if boundary is MonitorBoundary.MONITOR_START:
            return "Q_THRESHOLD_PRESENT_AT_MONITOR_START" if active else None
        if boundary is MonitorBoundary.GAP:
            return "Q_THRESHOLD_PRESENT_AFTER_GAP" if active else "Q_THRESHOLD_NOT_PRESENT_AFTER_GAP"
        if boundary is MonitorBoundary.RECONNECT:
            return "Q_THRESHOLD_PRESENT_AFTER_RECONNECT" if active else "Q_THRESHOLD_NOT_PRESENT_AFTER_RECONNECT"
    raise ValueError(f"unsupported monitor boundary: {boundary}")


def _transition_event_name(config: NegativeMonitorConfig, active: bool) -> str:
    if config.condition is NegativeCondition.P_NEGATIVE:
        return "NEGATIVE_START" if active else "NEGATIVE_END"
    if config.condition is NegativeCondition.Q_THRESHOLD:
        return "Q_THRESHOLD_START" if active else "Q_THRESHOLD_END"
    raise ValueError(f"unsupported monitor condition: {config.condition}")


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
            was_active = key in runtime.active_keys
            is_active = _condition_active(runtime.config, values[key])
            name = _boundary_event_name(runtime.config, boundary, is_active)
            if boundary is not MonitorBoundary.MONITOR_START:
                if not is_active and not (was_initialized and was_active):
                    name = None
            if is_active:
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
            is_active = _condition_active(runtime.config, values[key])
            was_active = key in runtime.active_keys
            if key not in runtime.initialized_keys:
                runtime.initialized_keys.add(key)
                if is_active:
                    runtime.active_keys.add(key)
                    events.append(
                        NegativeMonitorEvent(
                            _boundary_event_name(
                                runtime.config,
                                MonitorBoundary.MONITOR_START,
                                True,
                            ),
                            key.phase,
                            key.measurement,
                            cycle_id,
                            sample.timing.cycle_finished_utc,
                            values[key],
                            "MONITOR_START",
                        )
                    )
                continue
            if not was_active and is_active:
                runtime.active_keys.add(key)
                events.append(
                    NegativeMonitorEvent(
                        _transition_event_name(runtime.config, True),
                        key.phase,
                        key.measurement,
                        cycle_id,
                        sample.timing.cycle_finished_utc,
                        values[key],
                        "EXACT",
                    )
                )
            elif was_active and not is_active:
                runtime.active_keys.discard(key)
                events.append(
                    NegativeMonitorEvent(
                        _transition_event_name(runtime.config, False),
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
            key = ConditionKey(event.phase, event.measurement)
            if key in runtime.active_keys:
                first_activation = event
                break
    return NegativeMonitorEvaluation(
        tuple(events),
        active,
        aggregate_active,
        first_activation,
        before_active and not aggregate_active,
    )
