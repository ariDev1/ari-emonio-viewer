import asyncio

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.characterization_service import (
    CHARACTERIZATION_PWM_OWNER,
    CharacterizationState,
    Stage4BCharacterizationService,
)
from emonio_viewer.load_control.manual_pwm import ManualPwmState, ManualPwmStatus
from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.runtime.events import RuntimeEventBus


class FakeManualPwmService:
    def __init__(self) -> None:
        self.pwm_owner: str | None = None
        self.commands: list[float] = []
        self.sequence = 0
        self._status = self._make_status(0.0, 0.0)

    def _make_status(self, duty: float, actual: float) -> ManualPwmStatus:
        return ManualPwmStatus(
            state=ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-1",
            command_sequence=self.sequence,
            ack_result="APPLIED",
            rejection_reason=None,
            requested_duty_percent=duty,
            actual_duty_percent=actual,
            compare_ticks=0 if duty == 0.0 else 163,
            period_ticks=653,
            admissible=False,
        )

    def manual_pwm_status(self) -> ManualPwmStatus:
        return self._status

    def reserve_pwm_owner(self, owner: str) -> None:
        if self.pwm_owner is not None:
            raise Stage3AError("PWM_OWNER_RESERVED")
        self.pwm_owner = owner

    def release_pwm_owner(self, owner: str) -> None:
        if self.pwm_owner != owner:
            raise Stage3AError("PWM_OWNER_MISMATCH")
        self.pwm_owner = None

    async def run_reserved_pwm(self, duty_percent: float, *, owner: str) -> ManualPwmStatus:
        if self.pwm_owner != owner:
            raise Stage3AError("PWM_OWNER_MISMATCH")
        self.commands.append(float(duty_percent))
        self.sequence += 1
        actual = 0.0 if duty_percent == 0.0 else 100.0 * 163.0 / 653.0
        self._status = self._make_status(float(duty_percent), actual)
        return self._status


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-a"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(
            DeviceConfig(
                id="emonio-a",
                name="Emonio A",
                host="192.0.2.10",
                poll_interval_s=0.1,
            ),
        ),
    )


async def _wait_until(predicate, timeout_s: float = 0.5) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.001)


def test_close_aborts_active_sweep_with_acknowledged_off_before_unsubscribe() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        manual = FakeManualPwmService()
        service = Stage4BCharacterizationService(bus, _config(), manual_pwm=manual)
        await service.start()

        request = asyncio.create_task(
            service.run_auto_sweep(
                source_id="emonio-a",
                phase="A",
                duties=(25.0, 35.0),
            )
        )
        await _wait_until(
            lambda: manual.commands == [25.0]
            and manual.pwm_owner == CHARACTERIZATION_PWM_OWNER
        )

        await service.close()
        status = await request

        assert status.state is CharacterizationState.ABORTED
        assert status.last_error == "CHARACTERIZATION_ABORTED"
        assert status.safe_confirmed is True
        assert manual.commands == [25.0, 0.0]
        assert manual.pwm_owner is None

    asyncio.run(scenario())
