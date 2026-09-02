from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Sequence


ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT = 25.0
ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT = 75.0
MAX_SWEEP_POINTS = 51
MEASURED_CYCLES_PER_POINT = 3


@dataclass(frozen=True, slots=True)
class CharacterizationPoint:
    session_id: str
    mode: str
    source_id: str
    phase: str
    actuator_node_id: str
    actuator_boot_id: str
    command_sequence: int
    requested_duty_percent: float
    actual_duty_percent: float
    cycle_ids: tuple[int, int, int]
    p_samples_w: tuple[float, float, float]
    mean_p_w: float
    min_p_w: float
    max_p_w: float
    sample_stdev_p_w: float
    utc: str


def _finite_float(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def validate_sweep_duties(duties: Iterable[object]) -> tuple[float, ...]:
    values = tuple(_finite_float(value, field="duty_percent") for value in duties)
    if len(values) < 2:
        raise ValueError("at least two sweep points are required")
    if len(values) > MAX_SWEEP_POINTS:
        raise ValueError("too many sweep points")
    if len(set(values)) != len(values):
        raise ValueError("sweep points must be unique")
    for value in values:
        if value < ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT:
            raise ValueError("duty_percent is below the qualified characterization range")
        if value > ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT:
            raise ValueError("duty_percent is above the qualified characterization range")
    return values


def build_characterization_point(
    *,
    session_id: str,
    mode: str,
    source_id: str,
    phase: str,
    actuator_node_id: str,
    actuator_boot_id: str,
    command_sequence: int,
    requested_duty_percent: object,
    actual_duty_percent: object,
    cycle_ids: Sequence[int],
    p_samples_w: Sequence[object],
    utc: str,
) -> CharacterizationPoint:
    requested = _finite_float(requested_duty_percent, field="requested_duty_percent")
    if requested < ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT:
        raise ValueError("requested_duty_percent is below the qualified characterization range")
    if requested > ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT:
        raise ValueError("requested_duty_percent is above the qualified characterization range")

    actual = _finite_float(actual_duty_percent, field="actual_duty_percent")
    if actual < 0.0 or actual >= 100.0:
        raise ValueError("actual_duty_percent is outside the PWM protocol range")

    cycles = tuple(int(value) for value in cycle_ids)
    if len(cycles) != MEASURED_CYCLES_PER_POINT:
        raise ValueError("exactly three measurement cycle ids are required")
    if any(value < 0 for value in cycles):
        raise ValueError("cycle ids must be non-negative")

    p_values = tuple(_finite_float(value, field="p_samples_w") for value in p_samples_w)
    if len(p_values) != MEASURED_CYCLES_PER_POINT:
        raise ValueError("exactly three P samples are required")

    if not isinstance(command_sequence, int) or isinstance(command_sequence, bool) or command_sequence < 0:
        raise ValueError("command_sequence must be a non-negative integer")

    mean_p = statistics.fmean(p_values)
    min_p = min(p_values)
    max_p = max(p_values)
    stdev_p = statistics.stdev(p_values)

    return CharacterizationPoint(
        session_id=str(session_id),
        mode=str(mode),
        source_id=str(source_id),
        phase=str(phase),
        actuator_node_id=str(actuator_node_id),
        actuator_boot_id=str(actuator_boot_id),
        command_sequence=command_sequence,
        requested_duty_percent=requested,
        actual_duty_percent=actual,
        cycle_ids=(cycles[0], cycles[1], cycles[2]),
        p_samples_w=(p_values[0], p_values[1], p_values[2]),
        mean_p_w=mean_p,
        min_p_w=min_p,
        max_p_w=max_p,
        sample_stdev_p_w=stdev_p,
        utc=str(utc),
    )
