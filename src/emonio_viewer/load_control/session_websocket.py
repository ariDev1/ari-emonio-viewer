from __future__ import annotations

import asyncio
import math

from aiohttp import ClientSession, WSMsgType
from yarl import URL

from .model import ActuatorDescriptor
from .protocol import AckFrame, CommandFrame, HelloFrame, ProtocolError, decode_frame, encode_frame


def _positive_seconds(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return seconds


class WebSocketActuatorSession:
    """Persistent actuator protocol session over WebSocket.

    This class transports protocol frames only. It does not bind an actuator,
    authorize control, calculate demand, or perform automatic reconnection.
    """

    def __init__(
        self,
        descriptor: ActuatorDescriptor,
        *,
        connect_timeout_s: float,
        receive_timeout_s: float,
        client_session_factory=ClientSession,
        wait_for=asyncio.wait_for,
    ) -> None:
        if not isinstance(descriptor, ActuatorDescriptor):
            raise ValueError("descriptor must be ActuatorDescriptor")
        location = URL(descriptor.location)
        if location.scheme not in {"ws", "wss"} or not location.host:
            raise ValueError("actuator location must be ws:// or wss://")
        self.descriptor = descriptor
        self._connect_timeout_s = _positive_seconds(connect_timeout_s, "connect_timeout_s")
        self._receive_timeout_s = _positive_seconds(receive_timeout_s, "receive_timeout_s")
        self._client_session_factory = client_session_factory
        self._wait_for = wait_for
        self._client = None
        self._websocket = None

    @property
    def connected(self) -> bool:
        return self._websocket is not None and not bool(getattr(self._websocket, "closed", False))

    async def _receive_text(self) -> str:
        if not self.connected:
            raise ConnectionError("actuator WebSocket is not connected")
        message = await self._wait_for(
            self._websocket.receive(),
            self._receive_timeout_s,
        )
        if message.type is not WSMsgType.TEXT or not isinstance(message.data, str):
            raise ProtocolError("actuator WebSocket frame must be text")
        return message.data

    async def connect(self) -> HelloFrame:
        if self.connected:
            raise RuntimeError("actuator WebSocket is already connected")
        self._client = self._client_session_factory()
        try:
            self._websocket = await self._wait_for(
                self._client.ws_connect(self.descriptor.location),
                self._connect_timeout_s,
            )
            frame = decode_frame(await self._receive_text())
            if not isinstance(frame, HelloFrame):
                raise ProtocolError("first actuator frame must be HELLO")
            return frame
        except Exception:
            await self.disconnect()
            raise

    async def send_command(self, command: CommandFrame) -> None:
        if not isinstance(command, CommandFrame):
            raise ValueError("command must be CommandFrame")
        if not self.connected:
            raise ConnectionError("actuator WebSocket is not connected")
        await self._websocket.send_str(encode_frame(command))

    async def receive_ack(self) -> AckFrame:
        frame = decode_frame(await self._receive_text())
        if not isinstance(frame, AckFrame):
            raise ProtocolError("expected ACK frame")
        return frame

    async def disconnect(self) -> None:
        websocket = self._websocket
        client = self._client
        self._websocket = None
        self._client = None
        if websocket is not None:
            await websocket.close()
        if client is not None:
            await client.close()
