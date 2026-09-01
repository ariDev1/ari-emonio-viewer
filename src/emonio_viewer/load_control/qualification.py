from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum

from .lan_discovery import LanActuatorDiscoveryService
from .model import ActuatorDescriptor, ThreePhasePower
from .protocol import HelloFrame, LOAD_CONTROL_PROTOCOL_VERSION
from .session_websocket import WebSocketActuatorSession


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


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__


class LoadControlQualificationService:
    """Own real WebSocket HELLO qualification without control authority."""

    def __init__(
        self,
        lan_discovery_service: LanActuatorDiscoveryService,
        *,
        connect_timeout_s: float = 3.0,
        receive_timeout_s: float = 2.0,
        session_factory=WebSocketActuatorSession,
        create_task=asyncio.create_task,
    ) -> None:
        self._lan_discovery_service = lan_discovery_service
        self._connect_timeout_s = connect_timeout_s
        self._receive_timeout_s = receive_timeout_s
        self._session_factory = session_factory
        self._create_task = create_task
        self._state = QualificationState.IDLE
        self._selected_descriptor: ActuatorDescriptor | None = None
        self._hello: HelloFrame | None = None
        self._session = None
        self._watch_task = None
        self._last_error: str | None = None

    def _resolve_descriptor(self, node_id: str) -> ActuatorDescriptor:
        if not isinstance(node_id, str) or not node_id:
            raise LoadControlQualificationError("node_id is required")
        matches = tuple(
            item
            for item in self._lan_discovery_service.last_result
            if item.node_id == node_id
        )
        if not matches:
            raise LoadControlQualificationError(
                "selected node_id is not in the latest LAN discovery result"
            )
        if len(matches) != 1:
            raise LoadControlQualificationError(
                "selected node_id is ambiguous in the latest LAN discovery result"
            )
        return matches[0]

    def status(self) -> QualificationStatus:
        hello = self._hello if self._state is QualificationState.QUALIFIED else None
        return QualificationStatus(
            state=self._state,
            connected=bool(self._session is not None and self._session.connected),
            hello_qualified=hello is not None,
            selected_node_id=(
                self._selected_descriptor.node_id
                if self._selected_descriptor is not None
                else None
            ),
            node_id=(hello.node_id if hello is not None else None),
            boot_id=(hello.boot_id if hello is not None else None),
            protocol_version=(hello.protocol_version if hello is not None else None),
            device_class=(hello.device_class if hello is not None else None),
            capabilities=(hello.capabilities if hello is not None else ()),
            p_max=(hello.p_max if hello is not None else None),
            location=(
                self._selected_descriptor.location
                if self._selected_descriptor is not None
                else None
            ),
            last_error=self._last_error,
        )

    async def connect(self, node_id: str) -> QualificationStatus:
        if self._session is not None and self._session.connected:
            raise LoadControlQualificationError(
                "a Stage-2 actuator connection is already open"
            )

        descriptor = self._resolve_descriptor(node_id)
        self._selected_descriptor = descriptor
        self._hello = None
        self._last_error = None
        self._state = QualificationState.DISCOVERED

        session = self._session_factory(
            descriptor,
            connect_timeout_s=self._connect_timeout_s,
            receive_timeout_s=self._receive_timeout_s,
        )
        self._session = session

        try:
            self._state = QualificationState.CONNECTING
            await session.open()
            self._state = QualificationState.HELLO_WAIT
            hello = await session.receive_hello()
            qualify_hello(descriptor, hello)
            self._hello = hello
            self._state = QualificationState.QUALIFIED
            self._watch_task = self._create_task(self._watch_disconnect(session))
            return self.status()
        except Exception as exc:
            self._hello = None
            self._last_error = _error_text(exc)
            self._state = QualificationState.REJECTED
            try:
                await session.disconnect()
            finally:
                self._session = None
            return self.status()

    async def _watch_disconnect(self, session) -> None:
        try:
            await session.wait_for_disconnect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if session is self._session:
                self._last_error = _error_text(exc)
        finally:
            if session is self._session:
                self._session = None
                self._hello = None
                self._watch_task = None
                self._state = QualificationState.DISCONNECTED
                try:
                    await session.disconnect()
                except Exception as exc:
                    if self._last_error is None:
                        self._last_error = _error_text(exc)

    async def disconnect(self) -> QualificationStatus:
        had_selection = self._selected_descriptor is not None
        session = self._session
        watch_task = self._watch_task

        self._session = None
        self._watch_task = None
        self._hello = None

        if watch_task is not None and watch_task is not asyncio.current_task():
            watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await watch_task

        if session is not None:
            await session.disconnect()

        self._state = (
            QualificationState.DISCONNECTED if had_selection else QualificationState.IDLE
        )
        return self.status()

    async def close(self) -> None:
        await self.disconnect()
