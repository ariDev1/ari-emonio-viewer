from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from .model import ThreePhasePower


LOAD_CONTROL_PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """Raised when a load-control protocol frame is malformed or incompatible."""


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


def _power(name: str, value: ThreePhasePower, *, non_negative: bool) -> ThreePhasePower:
    if not isinstance(value, ThreePhasePower):
        raise ValueError(f"{name} must be ThreePhasePower")
    converted = ThreePhasePower(
        _finite(f"{name}.a", value.a),
        _finite(f"{name}.b", value.b),
        _finite(f"{name}.c", value.c),
    )
    if non_negative and min(converted.a, converted.b, converted.c) < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return converted


def _protocol_version(value: Any) -> int:
    version = _integer("protocol_version", value, minimum=1)
    if version != LOAD_CONTROL_PROTOCOL_VERSION:
        raise ValueError("unsupported protocol_version")
    return version


@dataclass(frozen=True, slots=True)
class HelloFrame:
    protocol_version: int
    node_id: str
    boot_id: str
    device_class: str
    capabilities: tuple[str, ...]
    p_max: ThreePhasePower

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        _text("node_id", self.node_id)
        _text("boot_id", self.boot_id)
        _text("device_class", self.device_class)
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(item, str) or not item for item in self.capabilities
        ):
            raise ValueError("capabilities must be a tuple of non-empty text values")
        limits = _power("p_max", self.p_max, non_negative=True)
        if min(limits.a, limits.b, limits.c) <= 0.0:
            raise ValueError("p_max must be > 0 on all phases")


@dataclass(frozen=True, slots=True)
class CommandFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    emonio_device_id: str
    measurement_cycle_id: int
    measurement_utc: str
    command_utc: str
    control_enabled: bool
    p_reserve: float
    measured_p: ThreePhasePower
    measured_q: ThreePhasePower
    p_load_request: ThreePhasePower
    q_comp_request: ThreePhasePower

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        for name in (
            "viewer_session_id",
            "node_id",
            "boot_id",
            "emonio_device_id",
            "measurement_utc",
            "command_utc",
        ):
            _text(name, getattr(self, name))
        _integer("sequence", self.sequence, minimum=1)
        _integer("measurement_cycle_id", self.measurement_cycle_id, minimum=0)
        if not isinstance(self.control_enabled, bool):
            raise ValueError("control_enabled must be boolean")
        reserve = _finite("p_reserve", self.p_reserve)
        if reserve < 0.0 or (self.control_enabled and reserve <= 0.0):
            raise ValueError("p_reserve is invalid for command state")
        _power("measured_p", self.measured_p, non_negative=False)
        _power("measured_q", self.measured_q, non_negative=False)
        _power("p_load_request", self.p_load_request, non_negative=True)
        q_request = _power("q_comp_request", self.q_comp_request, non_negative=False)
        if (q_request.a, q_request.b, q_request.c) != (0.0, 0.0, 0.0):
            raise ValueError("q_comp_request must be zero in protocol V1")


@dataclass(frozen=True, slots=True)
class AckFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    ack_utc: str
    applied_p: ThreePhasePower
    result: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        for name in ("viewer_session_id", "node_id", "boot_id", "ack_utc", "result"):
            _text(name, getattr(self, name))
        _integer("sequence", self.sequence, minimum=1)
        _power("applied_p", self.applied_p, non_negative=True)


@dataclass(frozen=True, slots=True)
class StatusFrame:
    protocol_version: int
    node_id: str
    boot_id: str
    status_utc: str
    applied_p: ThreePhasePower
    state: str
    faults: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _protocol_version(self.protocol_version))
        for name in ("node_id", "boot_id", "status_utc", "state"):
            _text(name, getattr(self, name))
        _power("applied_p", self.applied_p, non_negative=True)
        if not isinstance(self.faults, tuple) or any(
            not isinstance(item, str) or not item for item in self.faults
        ):
            raise ValueError("faults must be a tuple of non-empty text values")


ProtocolFrame = HelloFrame | CommandFrame | AckFrame | StatusFrame


def _power_to_json(value: ThreePhasePower) -> dict[str, float]:
    return {"a": float(value.a), "b": float(value.b), "c": float(value.c)}


def _power_from_json(name: str, raw: Any) -> ThreePhasePower:
    if not isinstance(raw, dict) or set(raw) != {"a", "b", "c"}:
        raise ProtocolError(f"{name} fields do not match schema")
    try:
        return ThreePhasePower(float(raw["a"]), float(raw["b"]), float(raw["c"]))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtocolError(f"{name} is invalid") from exc


def frame_to_dict(frame: ProtocolFrame) -> dict[str, Any]:
    if isinstance(frame, HelloFrame):
        return {
            "message_type": "HELLO",
            "protocol_version": frame.protocol_version,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "device_class": frame.device_class,
            "capabilities": list(frame.capabilities),
            "p_max": _power_to_json(frame.p_max),
        }
    if isinstance(frame, CommandFrame):
        return {
            "message_type": "COMMAND",
            "protocol_version": frame.protocol_version,
            "viewer_session_id": frame.viewer_session_id,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "sequence": frame.sequence,
            "emonio_device_id": frame.emonio_device_id,
            "measurement_cycle_id": frame.measurement_cycle_id,
            "measurement_utc": frame.measurement_utc,
            "command_utc": frame.command_utc,
            "control_enabled": frame.control_enabled,
            "p_reserve": float(frame.p_reserve),
            "measured_p": _power_to_json(frame.measured_p),
            "measured_q": _power_to_json(frame.measured_q),
            "p_load_request": _power_to_json(frame.p_load_request),
            "q_comp_request": _power_to_json(frame.q_comp_request),
        }
    if isinstance(frame, AckFrame):
        return {
            "message_type": "ACK",
            "protocol_version": frame.protocol_version,
            "viewer_session_id": frame.viewer_session_id,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "sequence": frame.sequence,
            "ack_utc": frame.ack_utc,
            "applied_p": _power_to_json(frame.applied_p),
            "result": frame.result,
        }
    if isinstance(frame, StatusFrame):
        return {
            "message_type": "STATUS",
            "protocol_version": frame.protocol_version,
            "node_id": frame.node_id,
            "boot_id": frame.boot_id,
            "status_utc": frame.status_utc,
            "applied_p": _power_to_json(frame.applied_p),
            "state": frame.state,
            "faults": list(frame.faults),
        }
    raise TypeError("unsupported protocol frame")


def encode_frame(frame: ProtocolFrame) -> str:
    try:
        return json.dumps(
            frame_to_dict(frame),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("cannot serialize protocol frame") from exc


def _require_fields(raw: dict[str, Any], fields: set[str]) -> None:
    if set(raw) != fields:
        raise ProtocolError("protocol frame fields do not match schema")


def decode_frame(text: str) -> ProtocolFrame:
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
        if message_type == "HELLO":
            _require_fields(raw, {"message_type", "protocol_version", "node_id", "boot_id", "device_class", "capabilities", "p_max"})
            if not isinstance(raw["capabilities"], list):
                raise ProtocolError("capabilities must be a list")
            return HelloFrame(
                protocol_version=raw["protocol_version"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                device_class=raw["device_class"],
                capabilities=tuple(raw["capabilities"]),
                p_max=_power_from_json("p_max", raw["p_max"]),
            )
        if message_type == "COMMAND":
            _require_fields(raw, {"message_type", "protocol_version", "viewer_session_id", "node_id", "boot_id", "sequence", "emonio_device_id", "measurement_cycle_id", "measurement_utc", "command_utc", "control_enabled", "p_reserve", "measured_p", "measured_q", "p_load_request", "q_comp_request"})
            return CommandFrame(
                protocol_version=raw["protocol_version"],
                viewer_session_id=raw["viewer_session_id"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                sequence=raw["sequence"],
                emonio_device_id=raw["emonio_device_id"],
                measurement_cycle_id=raw["measurement_cycle_id"],
                measurement_utc=raw["measurement_utc"],
                command_utc=raw["command_utc"],
                control_enabled=raw["control_enabled"],
                p_reserve=raw["p_reserve"],
                measured_p=_power_from_json("measured_p", raw["measured_p"]),
                measured_q=_power_from_json("measured_q", raw["measured_q"]),
                p_load_request=_power_from_json("p_load_request", raw["p_load_request"]),
                q_comp_request=_power_from_json("q_comp_request", raw["q_comp_request"]),
            )
        if message_type == "ACK":
            _require_fields(raw, {"message_type", "protocol_version", "viewer_session_id", "node_id", "boot_id", "sequence", "ack_utc", "applied_p", "result"})
            return AckFrame(
                protocol_version=raw["protocol_version"],
                viewer_session_id=raw["viewer_session_id"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                sequence=raw["sequence"],
                ack_utc=raw["ack_utc"],
                applied_p=_power_from_json("applied_p", raw["applied_p"]),
                result=raw["result"],
            )
        if message_type == "STATUS":
            _require_fields(raw, {"message_type", "protocol_version", "node_id", "boot_id", "status_utc", "applied_p", "state", "faults"})
            if not isinstance(raw["faults"], list):
                raise ProtocolError("faults must be a list")
            return StatusFrame(
                protocol_version=raw["protocol_version"],
                node_id=raw["node_id"],
                boot_id=raw["boot_id"],
                status_utc=raw["status_utc"],
                applied_p=_power_from_json("applied_p", raw["applied_p"]),
                state=raw["state"],
                faults=tuple(raw["faults"]),
            )
    except ProtocolError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProtocolError("protocol frame is invalid") from exc
    raise ProtocolError("unknown message_type")
