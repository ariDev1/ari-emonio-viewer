import asyncio
from dataclasses import dataclass, replace

from aiohttp import WSMsgType
import pytest

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.protocol import (
    AckFrame,
    CommandFrame,
    HelloFrame,
    ProtocolError,
    decode_frame,
    encode_frame,
)
from emonio_viewer.load_control.session_websocket import WebSocketActuatorSession


@dataclass
class FakeMessage:
    type: WSMsgType
    data: object


class FakeWebSocket:
    def __init__(self, messages) -> None:
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    async def receive(self):
        return self.messages.pop(0)

    async def send_str(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


class FakeClientSession:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket
        self.locations = []
        self.ws_options = []
        self.closed = False

    async def ws_connect(self, location: str, **kwargs):
        self.locations.append(location)
        self.ws_options.append(kwargs)
        return self.websocket

    async def close(self) -> None:
        self.closed = True


def _descriptor() -> ActuatorDescriptor:
    return ActuatorDescriptor(
        node_id="ARI-LOAD-001",
        location="ws://192.168.20.44:8765/control",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1200.0, 1200.0, 1200.0),
    )


def _hello() -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id="BOOT-001",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1200.0, 1200.0, 1200.0),
    )


def _command() -> CommandFrame:
    return CommandFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-001",
        node_id="ARI-LOAD-001",
        boot_id="BOOT-001",
        sequence=7,
        emonio_device_id="emonio-example",
        measurement_cycle_id=42,
        measurement_utc="2026-09-01T12:00:00+00:00",
        command_utc="2026-09-01T12:00:00.100000+00:00",
        control_enabled=True,
        p_reserve=30.0,
        measured_p=ThreePhasePower(-420.0, 30.0, 30.0),
        measured_q=ThreePhasePower(10.0, 20.0, 30.0),
        p_load_request=ThreePhasePower(450.0, 0.0, 0.0),
        q_comp_request=ThreePhasePower(0.0, 0.0, 0.0),
    )


def _ack() -> AckFrame:
    command = _command()
    return AckFrame(
        protocol_version=1,
        viewer_session_id=command.viewer_session_id,
        node_id=command.node_id,
        boot_id=command.boot_id,
        sequence=command.sequence,
        ack_utc="2026-09-01T12:00:00.200000+00:00",
        applied_p=command.p_load_request,
        result="APPLIED",
    )


def _session(websocket: FakeWebSocket, *, wait_for=asyncio.wait_for):
    client = FakeClientSession(websocket)
    return (
        WebSocketActuatorSession(
            _descriptor(),
            connect_timeout_s=0.25,
            receive_timeout_s=0.15,
            client_session_factory=lambda: client,
            wait_for=wait_for,
        ),
        client,
    )


def test_websocket_session_supports_open_then_receive_hello() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.TEXT, encode_frame(_hello()))])
        session, client = _session(websocket)

        await session.open()
        assert session.connected is True
        assert client.locations == ["ws://192.168.20.44:8765/control"]
        assert client.ws_options == [{"autoping": True, "heartbeat": 2.0}]
        assert len(websocket.messages) == 1

        received_hello = await session.receive_hello()
        assert received_hello == _hello()
        assert websocket.messages == []
        assert websocket.sent == []

        await session.disconnect()

    asyncio.run(scenario())


def test_websocket_session_rejects_non_hello_first_application_frame() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.TEXT, encode_frame(_ack()))])
        session, client = _session(websocket)

        await session.open()
        with pytest.raises(ProtocolError, match="first actuator frame must be HELLO"):
            await session.receive_hello()

        assert websocket.sent == []
        assert websocket.closed is True
        assert client.closed is True
        assert session.connected is False

    asyncio.run(scenario())


def test_websocket_session_rejects_malformed_json_first_frame() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.TEXT, "{not-json")])
        session, _client = _session(websocket)

        await session.open()
        with pytest.raises(ProtocolError, match="invalid protocol JSON"):
            await session.receive_hello()

        assert websocket.sent == []
        assert session.connected is False

    asyncio.run(scenario())


def test_websocket_session_rejects_binary_first_frame() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.BINARY, b"binary")])
        session, _client = _session(websocket)

        await session.open()
        with pytest.raises(ProtocolError, match="frame must be text"):
            await session.receive_hello()

        assert websocket.sent == []
        assert session.connected is False

    asyncio.run(scenario())


def test_websocket_session_disconnect_watcher_sends_no_frame() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket(
            [
                FakeMessage(WSMsgType.TEXT, encode_frame(_hello())),
                FakeMessage(WSMsgType.CLOSE, ""),
            ]
        )
        session, _client = _session(websocket)

        await session.connect()
        await session.wait_for_disconnect()

        assert websocket.sent == []

        await session.disconnect()

    asyncio.run(scenario())


def test_websocket_session_uses_explicit_timeouts_and_protocol_frames() -> None:
    async def scenario() -> None:
        hello = _hello()
        command = _command()
        ack = _ack()
        websocket = FakeWebSocket(
            [
                FakeMessage(WSMsgType.TEXT, encode_frame(hello)),
                FakeMessage(WSMsgType.TEXT, encode_frame(ack)),
            ]
        )
        client = FakeClientSession(websocket)
        observed_timeouts = []

        async def fake_wait_for(awaitable, timeout):
            observed_timeouts.append(timeout)
            return await awaitable

        session = WebSocketActuatorSession(
            _descriptor(),
            connect_timeout_s=0.25,
            receive_timeout_s=0.15,
            client_session_factory=lambda: client,
            wait_for=fake_wait_for,
        )

        received_hello = await session.connect()
        assert received_hello == hello
        assert client.locations == ["ws://192.168.20.44:8765/control"]

        await session.send_command(command)
        assert decode_frame(websocket.sent[0]) == command

        received_ack = await session.receive_ack()
        assert received_ack == ack
        assert observed_timeouts == [0.25, 0.15, 0.15]

        await session.disconnect()
        assert websocket.closed is True
        assert client.closed is True
        assert session.connected is False

    asyncio.run(scenario())


def test_websocket_session_rejects_command_for_different_boot() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.TEXT, encode_frame(_hello()))])
        client = FakeClientSession(websocket)
        session = WebSocketActuatorSession(
            _descriptor(),
            connect_timeout_s=0.25,
            receive_timeout_s=0.15,
            client_session_factory=lambda: client,
        )
        await session.connect()

        wrong_boot = replace(_command(), boot_id="BOOT-OLD")
        with pytest.raises(ValueError, match="boot_id"):
            await session.send_command(wrong_boot)
        assert websocket.sent == []

        await session.disconnect()

    asyncio.run(scenario())
