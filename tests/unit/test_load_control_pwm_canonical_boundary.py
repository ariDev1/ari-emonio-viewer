import asyncio

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.characterization_service import Stage4BCharacterizationService
from emonio_viewer.load_control.manual_pwm import (
    PWM_DUTY_CONTROL_CAPABILITY,
    Stage3BManualPwmCommandService,
)
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import HelloFrame
from emonio_viewer.load_control.pwm_protocol import PwmAckFrame, PwmCommandFrame
from emonio_viewer.load_control.zero_export_service import Stage4CZeroExportControllerService
from emonio_viewer.runtime.events import RuntimeEventBus


class FakeQualifiedChannel:
    def __init__(self) -> None:
        self.current_hello = HelloFrame(
            protocol_version=1,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-PWM-FIELD-001",
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

    def push(self, item: object) -> None:
        self.frames.put_nowait(item)


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(),
    )


async def _wait_for_command(channel: FakeQualifiedChannel) -> PwmCommandFrame:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while not channel.sent_pwm:
        if loop.time() >= deadline:
            raise AssertionError("PWM command was not sent")
        await asyncio.sleep(0.001)
    return channel.sent_pwm[-1]


def test_qualified_rounded_ack_keeps_exact_viewer_command_as_canonical_requested_duty() -> None:
    async def scenario() -> None:
        channel = FakeQualifiedChannel()
        service = Stage3BManualPwmCommandService(
            RuntimeEventBus(),
            _config(),
            channel,
            viewer_session_id="VIEWER-PWM-FIELD-001",
        )
        await service.start()
        service.reserve_pwm_owner("FIELD_BOUNDARY_TEST")

        request = asyncio.create_task(
            service.run_reserved_pwm(74.609375, owner="FIELD_BOUNDARY_TEST")
        )
        command = await _wait_for_command(channel)
        channel.push(
            PwmAckFrame(
                protocol_version=1,
                viewer_session_id=command.viewer_session_id,
                node_id=command.node_id,
                boot_id=command.boot_id,
                sequence=command.sequence,
                result="APPLIED",
                requested_duty_percent=74.60938,
                actual_duty_percent=74.57886676875957,
                compare_ticks=487,
                period_ticks=653,
            )
        )

        status = await request
        assert command.duty_percent == 74.609375
        assert status.requested_duty_percent == 74.609375
        assert status.actual_duty_percent == 74.57886676875957
        assert status.compare_ticks == 487
        assert status.period_ticks == 653

        assert Stage4CZeroExportControllerService._qualified_command_ack(
            status,
            74.609375,
        )
        assert Stage4BCharacterizationService._qualified_active_pwm(
            status,
            expected_requested=74.609375,
        ) is status

        service.release_pwm_owner("FIELD_BOUNDARY_TEST")
        await service.close()

    asyncio.run(scenario())
