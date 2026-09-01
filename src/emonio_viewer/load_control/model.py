from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class ControlMode(str, Enum):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    TRIPPED = "TRIPPED"


class SessionState(str, Enum):
    UNBOUND = "UNBOUND"
    DISCOVERING = "DISCOVERING"
    UNAVAILABLE = "UNAVAILABLE"
    CONNECTING = "CONNECTING"
    VERIFYING = "VERIFYING"
    READY = "READY"
    SESSION_FAULT = "SESSION_FAULT"


class SafeState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SAFE_UNCONFIRMED = "SAFE_UNCONFIRMED"
    SAFE_CONFIRMED = "SAFE_CONFIRMED"


@dataclass(frozen=True, slots=True)
class ThreePhasePower:
    a: float
    b: float
    c: float


@dataclass(frozen=True, slots=True)
class LoadControlTiming:
    control_sample_max_age_s: float
    ack_timeout_s: float

    def __post_init__(self) -> None:
        for name in ("control_sample_max_age_s", "ack_timeout_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True, slots=True)
class PersistentLoadControlConfig:
    bound_emonio_device_id: str | None = None
    bound_actuator_node_id: str | None = None
    p_reserve: float | None = None
    operator_limit_a: float | None = None
    operator_limit_b: float | None = None
    operator_limit_c: float | None = None

    def __post_init__(self) -> None:
        for name in ("bound_emonio_device_id", "bound_actuator_node_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty text or None")

        for name in (
            "p_reserve",
            "operator_limit_a",
            "operator_limit_b",
            "operator_limit_c",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric or None")
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")
