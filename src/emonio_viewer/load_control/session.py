from __future__ import annotations

from collections import deque
from enum import Enum

from .model import ActuatorDescriptor, ThreePhasePower
from .protocol import AckFrame, CommandFrame, HelloFrame, LOAD_CONTROL_PROTOCOL_VERSION


class MockAckMode(str, Enum):
    EXACT = "EXACT"
    NONE = "NONE"
    WRONG_SEQUENCE = "WRONG_SEQUENCE"
    WRONG_NODE = "WRONG_NODE"
    WRONG_BOOT = "WRONG_BOOT"


class MockActuatorSession:
    """Deterministic Stage-1 actuator session with no network I/O."""

    def __init__(
        self,
        descriptor: ActuatorDescriptor,
        *,
        boot_id: str,
        ack_mode: MockAckMode = MockAckMode.EXACT,
    ) -> None:
        if not isinstance(boot_id, str) or not boot_id:
            raise ValueError("boot_id must be non-empty text")
        self.descriptor = descriptor
        self.boot_id = boot_id
        self.ack_mode = MockAckMode(ack_mode)
        self.connected = False
        self.applied_p = ThreePhasePower(0.0, 0.0, 0.0)
        self._sent: list[CommandFrame] = []
        self._acks: deque[AckFrame] = deque()

    @property
    def sent_commands(self) -> tuple[CommandFrame, ...]:
        return tuple(self._sent)

    async def connect(self) -> HelloFrame:
        self.connected = True
        return HelloFrame(
            protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
            node_id=self.descriptor.node_id,
            boot_id=self.boot_id,
            device_class=self.descriptor.device_class,
            capabilities=self.descriptor.capabilities,
            p_max=self.descriptor.p_max,
        )

    async def disconnect(self) -> None:
        self.connected = False
        self._acks.clear()

    async def send_command(self, command: CommandFrame) -> None:
        if not self.connected:
            raise ConnectionError("mock actuator is not connected")
        if command.node_id != self.descriptor.node_id:
            raise ValueError("command node_id does not match mock actuator")
        if command.boot_id != self.boot_id:
            raise ValueError("command boot_id does not match mock actuator")
        self._sent.append(command)
        if self.ack_mode is MockAckMode.NONE:
            return

        sequence = command.sequence
        node_id = self.descriptor.node_id
        boot_id = self.boot_id
        if self.ack_mode is MockAckMode.WRONG_SEQUENCE:
            sequence += 1
        elif self.ack_mode is MockAckMode.WRONG_NODE:
            node_id = f"{node_id}-WRONG"
        elif self.ack_mode is MockAckMode.WRONG_BOOT:
            boot_id = f"{boot_id}-WRONG"

        self.applied_p = command.p_load_request
        self._acks.append(
            AckFrame(
                protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
                viewer_session_id=command.viewer_session_id,
                node_id=node_id,
                boot_id=boot_id,
                sequence=sequence,
                ack_utc=command.command_utc,
                applied_p=self.applied_p,
                result="APPLIED",
            )
        )

    async def receive_ack(self) -> AckFrame | None:
        if not self._acks:
            return None
        return self._acks.popleft()

    def set_ack_mode(self, mode: MockAckMode) -> None:
        self.ack_mode = MockAckMode(mode)

    def lose_connection(self) -> None:
        self.connected = False
        self._acks.clear()

    def reboot(self, boot_id: str) -> None:
        if not isinstance(boot_id, str) or not boot_id:
            raise ValueError("boot_id must be non-empty text")
        self.boot_id = boot_id
        self.connected = False
        self.applied_p = ThreePhasePower(0.0, 0.0, 0.0)
        self._acks.clear()
