from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import ActuatorDescriptor, ThreePhasePower
from .protocol import HelloFrame, LOAD_CONTROL_PROTOCOL_VERSION


REQUIRED_DEVICE_CLASS = "ARI_LOAD_ACTUATOR"
REQUIRED_CAPABILITY = "ACTIVE_LOAD_CONTROL"


class QualificationState(str, Enum):
    IDLE = "IDLE"
    DISCOVERED = "DISCOVERED"
    CONNECTING = "CONNECTING"
    HELLO_WAIT = "HELLO_WAIT"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    DISCONNECTED = "DISCONNECTED"


class LoadControlQualificationError(RuntimeError):
    """Raised when a discovered actuator cannot be qualified safely."""


@dataclass(frozen=True, slots=True)
class QualificationStatus:
    state: QualificationState
    connected: bool
    hello_qualified: bool
    selected_node_id: str | None
    node_id: str | None
    boot_id: str | None
    protocol_version: int | None
    device_class: str | None
    capabilities: tuple[str, ...]
    p_max: ThreePhasePower | None
    location: str | None
    last_error: str | None


def qualify_hello(descriptor: ActuatorDescriptor, hello: HelloFrame) -> None:
    if not isinstance(descriptor, ActuatorDescriptor):
        raise ValueError("descriptor must be ActuatorDescriptor")
    if not isinstance(hello, HelloFrame):
        raise ValueError("hello must be HelloFrame")
    if hello.protocol_version != LOAD_CONTROL_PROTOCOL_VERSION:
        raise LoadControlQualificationError("protocol_version mismatch")
    if hello.node_id != descriptor.node_id:
        raise LoadControlQualificationError("node_id mismatch")
    if not hello.boot_id:
        raise LoadControlQualificationError("boot_id must be non-empty")
    if hello.device_class != REQUIRED_DEVICE_CLASS:
        raise LoadControlQualificationError("device_class mismatch")
    if REQUIRED_CAPABILITY not in hello.capabilities:
        raise LoadControlQualificationError(f"{REQUIRED_CAPABILITY} capability missing")
    if hello.p_max.a != descriptor.p_max.a:
        raise LoadControlQualificationError("p_max.a mismatch")
    if hello.p_max.b != descriptor.p_max.b:
        raise LoadControlQualificationError("p_max.b mismatch")
    if hello.p_max.c != descriptor.p_max.c:
        raise LoadControlQualificationError("p_max.c mismatch")
