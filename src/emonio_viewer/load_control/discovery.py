from __future__ import annotations

from .model import ActuatorDescriptor


class MockActuatorDiscovery:
    """Deterministic Stage-1 discovery source. It never grants control authority."""

    def __init__(self, visible: tuple[ActuatorDescriptor, ...] = ()) -> None:
        self._visible = tuple(visible)

    def set_visible(self, visible: tuple[ActuatorDescriptor, ...]) -> None:
        self._visible = tuple(visible)

    async def discover(self) -> tuple[ActuatorDescriptor, ...]:
        return self._visible
