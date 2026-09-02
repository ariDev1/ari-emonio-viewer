from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


ACTIVE_DUTY_MIN_PERCENT = 25.0
ACTIVE_DUTY_MAX_PERCENT = 75.0
SAFE_DUTY_PERCENT = 0.0


class PControlDecision(str, Enum):
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    DECREASE = "DECREASE"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"


@dataclass(frozen=True, slots=True)
class PControlProposal:
    decision: PControlDecision
    proposed_duty_percent: float
    low_w: float
    high_w: float


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validated_confirmed_duty(value: float) -> float:
    duty = _finite("confirmed_duty_percent", value)
    if duty == SAFE_DUTY_PERCENT:
        return duty
    if ACTIVE_DUTY_MIN_PERCENT <= duty <= ACTIVE_DUTY_MAX_PERCENT:
        return duty
    raise ValueError("confirmed_duty_percent is outside the Stage 4A qualified window")


def calculate_p_control_proposal(
    *,
    measured_p_w: float,
    p_target_w: float,
    p_deadband_w: float,
    confirmed_duty_percent: float,
    duty_step_percent: float,
) -> PControlProposal:
    measured_p = _finite("measured_p_w", measured_p_w)
    target = _finite("p_target_w", p_target_w)
    deadband = _finite("p_deadband_w", p_deadband_w)
    duty = _validated_confirmed_duty(confirmed_duty_percent)
    step = _finite("duty_step_percent", duty_step_percent)

    if deadband < 0.0:
        raise ValueError("p_deadband_w must be >= 0")
    if step <= 0.0:
        raise ValueError("duty_step_percent must be > 0")

    low = target - deadband
    high = target + deadband

    if measured_p < low:
        if duty == ACTIVE_DUTY_MAX_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_HIGH, duty, low, high)
        if duty == SAFE_DUTY_PERCENT:
            return PControlProposal(
                PControlDecision.INCREASE,
                ACTIVE_DUTY_MIN_PERCENT,
                low,
                high,
            )
        return PControlProposal(
            PControlDecision.INCREASE,
            min(duty + step, ACTIVE_DUTY_MAX_PERCENT),
            low,
            high,
        )

    if measured_p > high:
        if duty == SAFE_DUTY_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_LOW, duty, low, high)
        if duty == ACTIVE_DUTY_MIN_PERCENT:
            return PControlProposal(
                PControlDecision.DECREASE,
                SAFE_DUTY_PERCENT,
                low,
                high,
            )
        return PControlProposal(
            PControlDecision.DECREASE,
            max(duty - step, ACTIVE_DUTY_MIN_PERCENT),
            low,
            high,
        )

    return PControlProposal(PControlDecision.HOLD, duty, low, high)
