from __future__ import annotations

from dataclasses import dataclass
import math

from .model import ThreePhasePower


@dataclass(frozen=True, slots=True)
class PhaseControlResult:
    error: float
    raw_request: float
    limited_request: float
    limited_min: bool
    limited_max: bool


@dataclass(frozen=True, slots=True)
class ThreePhaseControlResult:
    a: PhaseControlResult
    b: PhaseControlResult
    c: PhaseControlResult


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def calculate_phase_request(
    *,
    measured_p: float,
    p_reserve: float,
    acknowledged_p: float,
    p_limit: float,
) -> PhaseControlResult:
    measured_p = _finite("measured_p", measured_p)
    p_reserve = _finite("p_reserve", p_reserve)
    acknowledged_p = _finite("acknowledged_p", acknowledged_p)
    p_limit = _finite("p_limit", p_limit)

    if p_reserve <= 0.0:
        raise ValueError("p_reserve must be > 0")
    if acknowledged_p < 0.0:
        raise ValueError("acknowledged_p must be >= 0")
    if p_limit <= 0.0:
        raise ValueError("p_limit must be > 0")

    error = p_reserve - measured_p
    raw_request = acknowledged_p + error
    limited_request = min(max(raw_request, 0.0), p_limit)

    return PhaseControlResult(
        error=error,
        raw_request=raw_request,
        limited_request=limited_request,
        limited_min=raw_request < 0.0,
        limited_max=raw_request > p_limit,
    )


def calculate_three_phase_request(
    *,
    measured_p: ThreePhasePower,
    p_reserve: float,
    acknowledged_p: ThreePhasePower,
    p_limit: ThreePhasePower,
) -> ThreePhaseControlResult:
    return ThreePhaseControlResult(
        a=calculate_phase_request(
            measured_p=measured_p.a,
            p_reserve=p_reserve,
            acknowledged_p=acknowledged_p.a,
            p_limit=p_limit.a,
        ),
        b=calculate_phase_request(
            measured_p=measured_p.b,
            p_reserve=p_reserve,
            acknowledged_p=acknowledged_p.b,
            p_limit=p_limit.b,
        ),
        c=calculate_phase_request(
            measured_p=measured_p.c,
            p_reserve=p_reserve,
            acknowledged_p=acknowledged_p.c,
            p_limit=p_limit.c,
        ),
    )
