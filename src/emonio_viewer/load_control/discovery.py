from __future__ import annotations

from collections.abc import Mapping
import math

from .model import ActuatorDescriptor, ThreePhasePower


LOAD_CONTROL_MDNS_SERVICE_TYPE = "_ari-emonio-load._tcp.local."


def _property_text(properties: Mapping[bytes, bytes], name: str) -> str:
    raw = properties.get(name.encode("ascii"))
    if not isinstance(raw, bytes) or not raw:
        raise ValueError(f"mDNS property {name} is required")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"mDNS property {name} must be UTF-8") from exc
    if not value:
        raise ValueError(f"mDNS property {name} is required")
    return value


def _positive_power(properties: Mapping[bytes, bytes], name: str) -> float:
    text = _property_text(properties, name)
    try:
        value = float(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"mDNS property {name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"mDNS property {name} must be finite and > 0")
    return value


def parse_mdns_descriptor(
    *,
    address: str,
    port: int,
    properties: Mapping[bytes, bytes],
) -> ActuatorDescriptor:
    """Map one resolved DNS-SD service record to a non-authoritative descriptor."""
    if not isinstance(address, str) or not address:
        raise ValueError("mDNS address must be non-empty text")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("mDNS port must be integer in range 1..65535")
    if not isinstance(properties, Mapping):
        raise ValueError("mDNS properties must be a mapping")

    node_id = _property_text(properties, "node_id")
    device_class = _property_text(properties, "device_class")
    capabilities_text = _property_text(properties, "capabilities")
    capabilities = tuple(item.strip() for item in capabilities_text.split(",") if item.strip())
    if not capabilities:
        raise ValueError("mDNS capabilities must not be empty")

    path = _property_text(properties, "ws_path")
    if not path.startswith("/"):
        raise ValueError("mDNS ws_path must start with /")

    return ActuatorDescriptor(
        node_id=node_id,
        location=f"ws://{address}:{port}{path}",
        device_class=device_class,
        capabilities=capabilities,
        p_max=ThreePhasePower(
            _positive_power(properties, "p_max_a_w"),
            _positive_power(properties, "p_max_b_w"),
            _positive_power(properties, "p_max_c_w"),
        ),
    )


class MockActuatorDiscovery:
    """Deterministic Stage-1 discovery source. It never grants control authority."""

    def __init__(self, visible: tuple[ActuatorDescriptor, ...] = ()) -> None:
        self._visible = tuple(visible)

    def set_visible(self, visible: tuple[ActuatorDescriptor, ...]) -> None:
        self._visible = tuple(visible)

    async def discover(self) -> tuple[ActuatorDescriptor, ...]:
        return self._visible
