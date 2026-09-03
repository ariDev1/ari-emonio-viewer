import asyncio

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.diagnostic_log import LoadControlDiagnosticLog
from emonio_viewer.load_control.manual_pwm import (
    ManualPwmState,
    PWM_DUTY_CONTROL_CAPABILITY,
    Stage3BManualPwmCommandService,
)
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import HelloFrame
from emonio_viewer.load_control.pwm_protocol import PwmAckFrame, PwmCommandFrame
from emonio_viewer.runtime.events import RuntimeEventBus


class FakeQualifiedChannel:
    def __init__(self) -> None:
        self.sent_pwm: list[PwmCommandFrame] = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self.current_hello = HelloFrame(
            protocol_version=1,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-PWM-DIAG-001",
            device_class="ARI_LOAD_ACTUATOR",
            capabilities=("ACTIVE_LOAD_CONTROL", PWM_DUTY_CONTROL_CAPABILITY),
            p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
        )

    def hello(self) -> HelloFrame:
        return self.current_hello

    async def send_pwm(self, command: PwmCommandFrame) -> None:
        self.sent_pwm.append(command)

    async def receive(self, timeout_s: float):
        return await asyncio.wait_for(self.frames.get(), timeout_s)

    def receive_nowait(self):
        return self.frames.get_nowait()


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(),
    )


async def _wait_for_pwm(channel: FakeQualifiedChannel) -> PwmCommandFrame:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while not channel.sent_pwm:
        if loop.time() >= deadline:
            raise AssertionError("expected one PWM command")
        await asyncio.sleep(0.001)
    return channel.sent_pwm[0]


def test_requested_duty_mismatch_logs_command_and_ack_echo_without_weakening_rejection() -> None:
    async def scenario() -> None:
        diagnostic_log = LoadControlDiagnosticLog()
        channel = FakeQualifiedChannel()
        service = Stage3BManualPwmCommandService(
            RuntimeEventBus(),
            _config(),
            channel,
            viewer_session_id="VIEWER-PWM-DIAG-001",
            diagnostic_log=diagnostic_log,
        )
        await service.start()

        request = asyncio.create_task(service.run_manual_pwm(74.609375))
        command = await _wait_for_pwm(channel)
        channel.frames.put_nowait(
            PwmAckFrame(
                protocol_version=1,
                viewer_session_id=command.viewer_session_id,
                node_id=command.node_id,
                boot_id=command.boot_id,
                sequence=command.sequence,
                result="APPLIED",
                requested_duty_percent=74.60935,
                actual_duty_percent=74.57886676875957,
                compare_ticks=487,
                period_ticks=653,
            )
        )

        result = await request
        assert result.state is ManualPwmState.REJECTED
        assert result.rejection_reason == "PWM_ACK_REQUESTED_DUTY_MISMATCH"
        assert len(channel.sent_pwm) == 1

        rejected = [item for item in diagnostic_log.recent() if item.event == "PWM_COMMAND_REJECTED"]
        assert len(rejected) == 1
        line = rejected[0].line
        assert 'reason="PWM_ACK_REQUESTED_DUTY_MISMATCH"' in line
        assert "commanded_duty_percent=74.609375" in line
        assert "ack_requested_duty_percent=74.60935" in line

        await service.close()

    asyncio.run(scenario())
