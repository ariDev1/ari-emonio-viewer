from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


SAFE_OFF_DUTY_PERCENT = 0.0
ACTIVE_DUTY_MIN_PERCENT = 25.0
ACTIVE_DUTY_MAX_PERCENT = 75.0


class ZeroExportAction(str, Enum):
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    DECREASE = "DECREASE"
    LIMIT_HIGH = "LIMIT_HIGH"
    SAFE_OFF = "SAFE_OFF"


@dataclass(frozen=True, slots=True)
class ZeroExportDecision:
    action: ZeroExportAction
    next_duty_percent: float
    lower_bracket_duty_percent: float | None
    upper_bracket_duty_percent: float | None


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _confirmed_duty(value: object) -> float:
    duty = _finite("confirmed_duty_percent", value)
    if duty == SAFE_OFF_DUTY_PERCENT:
        return duty
    if ACTIVE_DUTY_MIN_PERCENT <= duty <= ACTIVE_DUTY_MAX_PERCENT:
        return duty
    raise ValueError("confirmed_duty_percent is outside the qualified control window")


def _bracket(name: str, value: object | None) -> float | None:
    if value is None:
        return None
    duty = _finite(name, value)
    if SAFE_OFF_DUTY_PERCENT <= duty <= ACTIVE_DUTY_MAX_PERCENT:
        return duty
    raise ValueError(f"{name} is outside the qualified control window")


def calculate_zero_export_step(
    *,
    measured_p_w: object,
    p_deadband_w: object,
    confirmed_duty_percent: object,
    lower_bracket_duty_percent: object | None,
    upper_bracket_duty_percent: object | None,
) -> ZeroExportDecision:
    """Return the next bounded zero-export duty command.

    The calculation uses only the sign of canonical active power relative to
    the configured deadband. It does not estimate load watts, use Q or PF, or
    apply a fixed watts-to-duty gain.
    """

    measured_p = _finite("measured_p_w", measured_p_w)
    deadband = _finite("p_deadband_w", p_deadband_w)
    if deadband < 0.0:
        raise ValueError("p_deadband_w must be non-negative")

    confirmed = _confirmed_duty(confirmed_duty_percent)
    lower = _bracket("lower_bracket_duty_percent", lower_bracket_duty_percent)
    upper = _bracket("upper_bracket_duty_percent", upper_bracket_duty_percent)

    if lower is not None and upper is not None and lower >= upper:
        # A time-varying load can invalidate an old bracket. Do not retain a
        # contradictory plant model. The current signed P observation below
        # decides which stale side is removed.
        pass

    if -deadband <= measured_p <= deadband:
        return ZeroExportDecision(
            action=ZeroExportAction.HOLD,
            next_duty_percent=confirmed,
            lower_bracket_duty_percent=lower,
            upper_bracket_duty_percent=upper,
        )

    if measured_p < -deadband:
        if upper is not None and confirmed >= upper:
            upper = None
        if confirmed == SAFE_OFF_DUTY_PERCENT:
            return ZeroExportDecision(
                action=ZeroExportAction.INCREASE,
                next_duty_percent=ACTIVE_DUTY_MIN_PERCENT,
                lower_bracket_duty_percent=lower,
                upper_bracket_duty_percent=upper,
            )

        lower = confirmed
        if confirmed >= ACTIVE_DUTY_MAX_PERCENT:
            return ZeroExportDecision(
                action=ZeroExportAction.LIMIT_HIGH,
                next_duty_percent=ACTIVE_DUTY_MAX_PERCENT,
                lower_bracket_duty_percent=lower,
                upper_bracket_duty_percent=upper,
            )

        if upper is not None and lower < upper:
            next_duty = (lower + upper) / 2.0
        else:
            next_duty = (confirmed + ACTIVE_DUTY_MAX_PERCENT) / 2.0
        return ZeroExportDecision(
            action=ZeroExportAction.INCREASE,
            next_duty_percent=min(next_duty, ACTIVE_DUTY_MAX_PERCENT),
            lower_bracket_duty_percent=lower,
            upper_bracket_duty_percent=upper,
        )

    if confirmed == SAFE_OFF_DUTY_PERCENT:
        return ZeroExportDecision(
            action=ZeroExportAction.SAFE_OFF,
            next_duty_percent=SAFE_OFF_DUTY_PERCENT,
            lower_bracket_duty_percent=lower,
            upper_bracket_duty_percent=upper,
        )

    if lower is not None and confirmed <= lower:
        lower = None
    upper = confirmed

    if confirmed <= ACTIVE_DUTY_MIN_PERCENT:
        return ZeroExportDecision(
            action=ZeroExportAction.DECREASE,
            next_duty_percent=SAFE_OFF_DUTY_PERCENT,
            lower_bracket_duty_percent=lower,
            upper_bracket_duty_percent=upper,
        )

    if lower is not None and lower < upper:
        next_duty = (lower + upper) / 2.0
    else:
        next_duty = (ACTIVE_DUTY_MIN_PERCENT + confirmed) / 2.0
    return ZeroExportDecision(
        action=ZeroExportAction.DECREASE,
        next_duty_percent=max(next_duty, ACTIVE_DUTY_MIN_PERCENT),
        lower_bracket_duty_percent=lower,
        upper_bracket_duty_percent=upper,
    )
