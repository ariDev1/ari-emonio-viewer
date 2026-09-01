from __future__ import annotations

import asyncio
import math

from aiohttp import ClientSession, WSMsgType
from yarl import URL

from .model import ActuatorDescriptor
from .protocol import (
    AckFrame,
    CommandFrame,
    HelloFrame,
    ProtocolError,
    StatusFrame,
    decode_frame,
    encode_frame,
)


ACTUATOR_WEBSOCKET_HEARTBEAT_S = 2.0
PostHelloFrame = AckFrame | StatusFrame


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
        self._hello: HelloFrame | None = None
        self._inbound: asyncio.Queue[PostHelloFrame | Exception] = asyncio.Queue()
        self._disconnect_event = asyncio.Event()
        self._receiver_task: asyncio.Task[None] | None = None

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

    async def open(self) -> None:
        if self.connected:
            raise RuntimeError("actuator WebSocket is already connected")
        self._inbound = asyncio.Queue()
        self._disconnect_event = asyncio.Event()
        self._receiver_task = None
        self._client = self._client_session_factory()
        try:
            self._websocket = await self._wait_for(
                self._client.ws_connect(
                    self.descriptor.location,
                    autoping=True,
                    heartbeat=ACTUATOR_WEBSOCKET_HEARTBEAT_S,
                ),
                self._connect_timeout_s,
            )
        except Exception:
            await self.disconnect()
            raise

    async def receive_hello(self) -> HelloFrame:
        if not self.connected:
            raise ConnectionError("actuator WebSocket is not connected")
        if self._hello is not None:
            raise RuntimeError("actuator HELLO was already received")
        try:
            frame = decode_frame(await self._receive_text())
            if not isinstance(frame, HelloFrame):
                raise ProtocolError("first actuator frame must be HELLO")
            self._hello = frame
            return frame
        except Exception:
            await self.disconnect()
            raise

    async def connect(self) -> HelloFrame:
        await self.open()
        return await self.receive_hello()

    def start_receive_loop(self) -> None:
        if not self.connected or self._hello is None:
            raise ConnectionError("actuator HELLO is not available for receive loop")
        if self._receiver_task is not None:
            raise RuntimeError("actuator receive loop is already running")
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        try:
            while self.connected:
                message = await self._websocket.receive()
                if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    await self._inbound.put(ConnectionError("actuator WebSocket disconnected"))
                    self._disconnect_event.set()
                    return
                if message.type is not WSMsgType.TEXT or not isinstance(message.data, str):
                    raise ProtocolError("actuator WebSocket frame must be text")
                frame = decode_frame(message.data)
                if not isinstance(frame, (AckFrame, StatusFrame)):
                    raise ProtocolError("unexpected post-HELLO frame")
                await self._inbound.put(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._inbound.put(exc)
            self._disconnect_event.set()

    async def receive_frame(self, timeout_s: float) -> PostHelloFrame:
        timeout = _positive_seconds(timeout_s, "timeout_s")
        if self._receiver_task is None:
            raise ConnectionError("actuator receive loop is not running")
        item = await self._wait_for(self._inbound.get(), timeout)
        if isinstance(item, Exception):
            raise item
        return item

    async def wait_for_disconnect(self) -> None:
        if self._receiver_task is None:
            raise ConnectionError("actuator receive loop is not running")
        await self._disconnect_event.wait()

    async def send_command(self, command: CommandFrame) -> None:
        if not isinstance(command, CommandFrame):
            raise ValueError("command must be CommandFrame")
        if not self.connected or self._hello is None:
            raise ConnectionError("actuator WebSocket is not connected")
        if command.node_id != self._hello.node_id:
            raise ValueError("command node_id does not match session HELLO")
        if command.boot_id != self._hello.boot_id:
            raise ValueError("command boot_id does not match session HELLO")
        await self._websocket.send_str(encode_frame(command))

    async def receive_ack(self) -> AckFrame:
        frame = await self.receive_frame(self._receive_timeout_s)
        if not isinstance(frame, AckFrame):
            raise ProtocolError("expected ACK frame")
        return frame

    async def disconnect(self) -> None:
        receiver_task = self._receiver_task
        websocket = self._websocket
        client = self._client
        self._receiver_task = None
        self._websocket = None
        self._client = None
        self._hello = None
        self._disconnect_event.set()
        if receiver_task is not None and receiver_task is not asyncio.current_task():
            if not receiver_task.done():
                receiver_task.cancel()
            try:
                await receiver_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if websocket is not None:
            await websocket.close()
        if client is not None:
            await client.close()
