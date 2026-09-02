from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from .protocol import LOAD_CONTROL_PROTOCOL_VERSION, ProtocolError


PWM_DUTY_MIN_PERCENT = 0.0
PWM_DUTY_MAX_EXCLUSIVE_PERCENT = 100.0


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _integer(name: str, value: Any, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be integer >= {minimum}")
    return value


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _protocol_version(value: Any) -> int:
    version = _integer("protocol_version", value, minimum=1)
    if version != LOAD_CONTROL_PROTOCOL_VERSION:
        raise ValueError("unsupported protocol_version")
    return version


def _duty_percent(name: str, value: Any) -> float:
    duty = _finite(name, value)
    if duty < PWM_DUTY_MIN_PERCENT or duty >= PWM_DUTY_MAX_EXCLUSIVE_PERCENT:
        raise ValueError(f"{name} must satisfy 0 <= duty < 100")
    return duty


@dataclass(frozen=True, slots=True)
class PwmCommandFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    duty_percent: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        for name in ("viewer_session_id", "node_id", "boot_id"):
            _text(name, getattr(self, name))
        _integer("sequence", self.sequence, minimum=1)
        object.__setattr__(self, "duty_percent", _duty_percent("duty_percent", self.duty_percent))


@dataclass(frozen=True, slots=True)
class PwmAckFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    result: str
    requested_duty_percent: float
    actual_duty_percent: float
    compare_ticks: int
    period_ticks: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        for name in ("viewer_session_id", "node_id", "boot_id", "result"):
            _text(name, getattr(self, name))
        _integer("sequence", self.sequence, minimum=1)
        requested = _duty_percent("requested_duty_percent", self.requested_duty_percent)
        actual = _duty_percent("actual_duty_percent", self.actual_duty_percent)
        compare_ticks = _integer("compare_ticks", self.compare_ticks, minimum=0)
        period_ticks = _integer("period_ticks", self.period_ticks, minimum=1)
        if compare_ticks >= period_ticks and compare_ticks != 0:
            raise ValueError("compare_ticks must be less than period_ticks")
        expected_actual = 0.0 if compare_ticks == 0 else (100.0 * compare_ticks / period_ticks)
        if not math.isclose(actual, expected_actual, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("actual_duty_percent does not match compare_ticks/period_ticks")
        object.__setattr__(self, "requested_duty_percent", requested)
        object.__setattr__(self, "actual_duty_percent", actual)


PwmProtocolFrame = PwmCommandFrame | PwmAckFrame


def pwm_frame_to_dict(frame: PwmProtocolFrame) -> dict[str, Any]:
    if isinstance(frame, PwmCommandFrame):
        return {
            "message_type": "PWM_COMMAND",
            "protocol_version": frame.protocol_version,
            "viewer_session_id": frame.viewer_session_id,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "sequence": frame.sequence,
            "duty_percent": float(frame.duty_percent),
        }
    if isinstance(frame, PwmAckFrame):
        return {
            "message_type": "PWM_ACK",
            "protocol_version": frame.protocol_version,
            "viewer_session_id": frame.viewer_session_id,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "sequence": frame.sequence,
            "result": frame.result,
            "requested_duty_percent": float(frame.requested_duty_percent),
            "actual_duty_percent": float(frame.actual_duty_percent),
            "compare_ticks": frame.compare_ticks,
            "period_ticks": frame.period_ticks,
        }
    raise TypeError("unsupported PWM protocol frame")


def encode_pwm_frame(frame: PwmProtocolFrame) -> str:
    try:
        return json.dumps(
            pwm_frame_to_dict(frame),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("cannot serialize PWM protocol frame") from exc


def _require_fields(raw: dict[str, Any], fields: set[str]) -> None:
    if set(raw) != fields:
        raise ProtocolError("PWM protocol frame fields do not match schema")


def decode_pwm_frame(text: str) -> PwmProtocolFrame:
    if not isinstance(text, str):
        raise ProtocolError("protocol frame must be text")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid protocol JSON") from exc
    if not isinstance(raw, dict):
        raise ProtocolError("protocol frame must be an object")

    message_type = raw.get("message_type")
    try:
        if message_type == "PWM_COMMAND":
            _require_fields(
                raw,
                {
                    "message_type",
                    "protocol_version",
                    "viewer_session_id",
                    "node_id",
                    "boot_id",
                    "sequence",
                    "duty_percent",
                },
            )
            return PwmCommandFrame(
                protocol_version=raw["protocol_version"],
                viewer_session_id=raw["viewer_session_id"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                sequence=raw["sequence"],
                duty_percent=raw["duty_percent"],
            )
        if message_type == "PWM_ACK":
            _require_fields(
                raw,
                {
                    "message_type",
                    "protocol_version",
                    "viewer_session_id",
                    "node_id",
                    "boot_id",
                    "sequence",
                    "result",
                    "requested_duty_percent",
                    "actual_duty_percent",
                    "compare_ticks",
                    "period_ticks",
                },
            )
            return PwmAckFrame(
                protocol_version=raw["protocol_version"],
                viewer_session_id=raw["viewer_session_id"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                sequence=raw["sequence"],
                result=raw["result"],
                requested_duty_percent=raw["requested_duty_percent"],
                actual_duty_percent=raw["actual_duty_percent"],
                compare_ticks=raw["compare_ticks"],
                period_ticks=raw["period_ticks"],
            )
    except ProtocolError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProtocolError("PWM protocol frame is invalid") from exc
    raise ProtocolError("unknown PWM message_type")
