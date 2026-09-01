from __future__ import annotations

from .discovery import MdnsActuatorDiscovery, MdnsDiscoveryBackend
from .discovery_zeroconf import ZeroconfMdnsBackend
from .model import ActuatorDescriptor


class LanActuatorDiscoveryService:
    """Operator-triggered LAN discovery with no control authority."""

    def __init__(self, *, backend: MdnsDiscoveryBackend | None = None) -> None:
        self._backend = backend or ZeroconfMdnsBackend()
        self._last_result: tuple[ActuatorDescriptor, ...] = ()

    @property
    def last_result(self) -> tuple[ActuatorDescriptor, ...]:
        return self._last_result

    async def scan(
        self,
        *,
        discovery_window_s: float,
        resolve_timeout_s: float,
    ) -> tuple[ActuatorDescriptor, ...]:
        discovery = MdnsActuatorDiscovery(
            discovery_window_s=discovery_window_s,
            resolve_timeout_s=resolve_timeout_s,
            backend=self._backend,
        )
        result = await discovery.discover()
        self._last_result = result
        return result
