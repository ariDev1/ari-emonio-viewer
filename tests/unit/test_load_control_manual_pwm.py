import asyncio
import json
import math

import pytest

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.manual_pwm import (
    ManualPwmState,
    PWM_DUTY_CONTROL_CAPABILITY,
    Stage3BManualPwmCommandService,
)
from emonio_viewer.load_control.protocol import HelloFrame
from emonio_viewer.load_control.pwm_protocol import (
    PwmAckFrame,
    PwmCommandFrame,
    decode_pwm_frame,
    encode_pwm_frame,
)
from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.runtime.events import RuntimeEventBus


class FakeQualifiedChannel:
    def __init__(self, hello: HelloFrame | None) -> None:
        self.current_hello = hello
        self.sent_pwm = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()

    def hello(self) -> HelloFrame | None:
        return self.current_hello

    async def send_pwm(self, command: PwmCommandFrame) -> None:
        self.sent_pwm.append(command)

    async def receive(self, timeout_s: float):
        item = await asyncio.wait_for(self.frames.get(), timeout_s)
        if isinstance(item, Exception):
            raise item
        return item

    def receive_nowait(self):
        return self.frames.get_nowait()

    def push(self, item: object) -> None:
        self.frames.put_nowait(item)


def _hello(*, pwm_capability: bool = True, boot_id: str = "BOOT-PWM-001") -> HelloFrame:
    capabilities = ["ACTIVE_LOAD_CONTROL"]
    if pwm_capability:
        capabilities.append(PWM_DUTY_CONTROL_CAPABILITY)
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id=boot_id,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=tuple(capabilities),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(),
    )


def _service(channel: FakeQualifiedChannel) -> Stage3BManualPwmCommandService:
    return Stage3BManualPwmCommandService(
        RuntimeEventBus(),
        _config(),
        channel,
        viewer_session_id="VIEWER-PWM-001",
    )


async def _wait_for_pwm(channel: FakeQualifiedChannel, *, count: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while len(channel.sent_pwm) < count:
        if loop.time() >= deadline:
            raise AssertionError(f"expected {count} PWM command(s), observed {len(channel.sent_pwm)}")
        await asyncio.sleep(0.001)


def _ack(command: PwmCommandFrame, *, actual: float, compare: int, period: int) -> PwmAckFrame:
    return PwmAckFrame(
        protocol_version=1,
        viewer_session_id=command.viewer_session_id,
        node_id=command.node_id,
        boot_id=command.boot_id,
        sequence=command.sequence,
        result="APPLIED",
        requested_duty_percent=command.duty_percent,
        actual_duty_percent=actual,
        compare_ticks=compare,
        period_ticks=period,
    )


def test_pwm_command_and_ack_round_trip_are_strict_and_deterministic() -> None:
    command = PwmCommandFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-PWM-001",
        node_id="ARI-LOAD-001",
        boot_id="BOOT-PWM-001",
        sequence=17,
        duty_percent=50.0,
    )
    ack = _ack(command, actual=50.07657, compare=327, period=653)

    command_text = encode_pwm_frame(command)
    ack_text = encode_pwm_frame(ack)

    assert command_text == encode_pwm_frame(command)
    assert ack_text == encode_pwm_frame(ack)
    assert decode_pwm_frame(command_text) == command
    assert decode_pwm_frame(ack_text) == ack
    assert json.loads(command_text) == {
        "boot_id": "BOOT-PWM-001",
        "duty_percent": 50.0,
        "message_type": "PWM_COMMAND",
        "node_id": "ARI-LOAD-001",
        "protocol_version": 1,
        "sequence": 17,
        "viewer_session_id": "VIEWER-PWM-001",
    }
    assert json.loads(ack_text) == {
        "actual_duty_percent": 50.07657,
        "boot_id": "BOOT-PWM-001",
        "compare_ticks": 327,
        "message_type": "PWM_ACK",
        "node_id": "ARI-LOAD-001",
        "period_ticks": 653,
        "protocol_version": 1,
        "requested_duty_percent": 50.0,
        "result": "APPLIED",
        "sequence": 17,
        "viewer_session_id": "VIEWER-PWM-001",
    }


@pytest.mark.parametrize("duty", [-0.001, 100.0, math.nan, math.inf, -math.inf])
def test_pwm_command_rejects_duty_outside_zero_inclusive_100_exclusive(duty: float) -> None:
    with pytest.raises(ValueError):
        PwmCommandFrame(
            protocol_version=1,
            viewer_session_id="VIEWER-PWM-001",
            node_id="ARI-LOAD-001",
            boot_id="BOOT-PWM-001",
            sequence=1,
            duty_percent=duty,
        )


def test_manual_pwm_requires_only_current_qualified_pwm_capable_actuator() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel(_hello())
        service = _service(channel)
        await service.start()

        initial = service.manual_pwm_status()
        assert initial.state is ManualPwmState.READY
        assert initial.admissible is True
        assert initial.requested_duty_percent is None
        assert initial.actual_duty_percent is None

        request = asyncio.create_task(service.run_manual_pwm(50.0))
        await _wait_for_pwm(channel, count=1)
        command = channel.sent_pwm[0]
        assert command.sequence == 1
        assert command.duty_percent == 50.0
        assert command.node_id == "ARI-LOAD-001"
        assert command.boot_id == "BOOT-PWM-001"
        channel.push(_ack(command, actual=50.07657, compare=327, period=653))

        applied = await request
        assert applied.state is ManualPwmState.APPLIED
        assert applied.requested_duty_percent == 50.0
        assert applied.actual_duty_percent == 50.07657
        assert applied.compare_ticks == 327
        assert applied.period_ticks == 653
        assert applied.command_sequence == 1
        assert applied.ack_result == "APPLIED"
        assert applied.admissible is True

        off_request = asyncio.create_task(service.run_manual_pwm(0.0))
        await _wait_for_pwm(channel, count=2)
        off_command = channel.sent_pwm[1]
        assert off_command.sequence == 2
        assert off_command.duty_percent == 0.0
        channel.push(_ack(off_command, actual=0.0, compare=0, period=653))

        off = await off_request
        assert off.state is ManualPwmState.OFF
        assert off.actual_duty_percent == 0.0
        assert off.compare_ticks == 0
        assert off.command_sequence == 2

        await service.close()

    asyncio.run(scenario())


def test_manual_pwm_rejects_unqualified_or_non_pwm_capable_actuator_without_send() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel(None)
        service = _service(channel)
        await service.start()
        with pytest.raises(Stage3AError, match="ACTUATOR_NOT_QUALIFIED"):
            await service.run_manual_pwm(25.0)
        assert channel.sent_pwm == []

        channel.current_hello = _hello(pwm_capability=False)
        with pytest.raises(Stage3AError, match="PWM_DUTY_CONTROL_NOT_SUPPORTED"):
            await service.run_manual_pwm(25.0)
        assert channel.sent_pwm == []
        assert service.manual_pwm_status().admissible is False

        await service.close()

    asyncio.run(scenario())


def test_manual_pwm_rejects_ack_identity_mismatch_and_does_not_retry() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel(_hello())
        service = _service(channel)
        await service.start()

        request = asyncio.create_task(service.run_manual_pwm(25.0))
        await _wait_for_pwm(channel, count=1)
        command = channel.sent_pwm[0]
        channel.push(
            PwmAckFrame(
                protocol_version=1,
                viewer_session_id=command.viewer_session_id,
                node_id=command.node_id,
                boot_id=command.boot_id,
                sequence=command.sequence + 1,
                result="APPLIED",
                requested_duty_percent=25.0,
                actual_duty_percent=100.0 * 163 / 653,
                compare_ticks=163,
                period_ticks=653,
            )
        )

        result = await request
        assert result.state is ManualPwmState.REJECTED
        assert result.rejection_reason == "PWM_ACK_SEQUENCE_MISMATCH"
        assert len(channel.sent_pwm) == 1

        await service.close()

    asyncio.run(scenario())
