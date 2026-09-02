import asyncio

import pytest

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.manual_pwm import (
    PWM_DUTY_CONTROL_CAPABILITY,
    Stage3BManualPwmCommandService,
)
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import HelloFrame
from emonio_viewer.load_control.pwm_protocol import PwmAckFrame, PwmCommandFrame
from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.runtime.events import RuntimeEventBus


OWNER = "STAGE4B_CHARACTERIZATION"


class FakeQualifiedChannel:
    def __init__(self) -> None:
        self.current_hello = HelloFrame(
            protocol_version=1,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-PWM-001",
            device_class="ARI_LOAD_ACTUATOR",
            capabilities=("ACTIVE_LOAD_CONTROL", PWM_DUTY_CONTROL_CAPABILITY),
            p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
        )
        self.sent_pwm: list[PwmCommandFrame] = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()

    def hello(self) -> HelloFrame | None:
        return self.current_hello

    async def send_pwm(self, command: PwmCommandFrame) -> None:
        self.sent_pwm.append(command)

    async def receive(self, timeout_s: float):
        return await asyncio.wait_for(self.frames.get(), timeout_s)

    def receive_nowait(self):
        return self.frames.get_nowait()

    def push_ack(self, command: PwmCommandFrame, *, actual: float, compare: int) -> None:
        self.frames.put_nowait(
            PwmAckFrame(
                protocol_version=1,
                viewer_session_id=command.viewer_session_id,
                node_id=command.node_id,
                boot_id=command.boot_id,
                sequence=command.sequence,
                result="APPLIED",
                requested_duty_percent=command.duty_percent,
                actual_duty_percent=actual,
                compare_ticks=compare,
                period_ticks=653,
            )
        )


def _service(channel: FakeQualifiedChannel) -> Stage3BManualPwmCommandService:
    config = RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(),
    )
    return Stage3BManualPwmCommandService(
        RuntimeEventBus(),
        config,
        channel,
        viewer_session_id="VIEWER-PWM-OWNER-001",
    )


async def _wait_for_send(channel: FakeQualifiedChannel, count: int) -> PwmCommandFrame:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while len(channel.sent_pwm) < count:
        if loop.time() >= deadline:
            raise AssertionError("PWM command was not sent")
        await asyncio.sleep(0.001)
    return channel.sent_pwm[count - 1]


def test_reserved_owner_blocks_manual_ui_command_without_send() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel()
        service = _service(channel)
        await service.start()

        service.reserve_pwm_owner(OWNER)
        assert service.pwm_owner == OWNER
        assert service.manual_pwm_status().admissible is False

        with pytest.raises(Stage3AError, match="PWM_OWNER_RESERVED"):
            await service.run_manual_pwm(25.0)
        assert channel.sent_pwm == []

        service.release_pwm_owner(OWNER)
        assert service.pwm_owner is None
        assert service.manual_pwm_status().admissible is True
        await service.close()

    asyncio.run(scenario())


def test_reserved_owner_uses_same_sequence_and_ack_path() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel()
        service = _service(channel)
        await service.start()
        service.reserve_pwm_owner(OWNER)

        request = asyncio.create_task(service.run_reserved_pwm(25.0, owner=OWNER))
        command = await _wait_for_send(channel, 1)
        assert command.sequence == 1
        channel.push_ack(command, actual=100.0 * 163 / 653, compare=163)
        result = await request
        assert result.command_sequence == 1
        assert result.requested_duty_percent == 25.0
        assert result.ack_result == "APPLIED"

        off_request = asyncio.create_task(service.run_reserved_pwm(0.0, owner=OWNER))
        off_command = await _wait_for_send(channel, 2)
        assert off_command.sequence == 2
        channel.push_ack(off_command, actual=0.0, compare=0)
        off = await off_request
        assert off.command_sequence == 2
        assert off.actual_duty_percent == 0.0

        service.release_pwm_owner(OWNER)
        await service.close()

    asyncio.run(scenario())


def test_wrong_owner_cannot_command_or_release_reservation() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel()
        service = _service(channel)
        await service.start()
        service.reserve_pwm_owner(OWNER)

        with pytest.raises(Stage3AError, match="PWM_OWNER_MISMATCH"):
            await service.run_reserved_pwm(25.0, owner="OTHER")
        with pytest.raises(Stage3AError, match="PWM_OWNER_MISMATCH"):
            service.release_pwm_owner("OTHER")
        assert channel.sent_pwm == []
        assert service.pwm_owner == OWNER

        service.release_pwm_owner(OWNER)
        await service.close()

    asyncio.run(scenario())
