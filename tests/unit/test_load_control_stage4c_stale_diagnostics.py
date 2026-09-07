import asyncio
from datetime import datetime, timezone

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.diagnostic_log import LoadControlDiagnosticLog
from emonio_viewer.load_control.manual_pwm import ManualPwmState, ManualPwmStatus
from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.load_control.zero_export_service import Stage4CZeroExportControllerService, ZeroExportControllerState
from emonio_viewer.runtime.events import RuntimeEventBus


UTC = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000

    def __call__(self) -> int:
        return self.value


class FakeManualPwmService:
    def __init__(self) -> None:
        self.pwm_owner: str | None = None
        self.sequence = 0
        self.commands: list[float] = []
        self._status = self._make_status(0.0)

    def _make_status(self, duty: float) -> ManualPwmStatus:
        return ManualPwmStatus(
            state=ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-TEST",
            command_sequence=self.sequence,
            ack_result="APPLIED",
            rejection_reason=None,
            requested_duty_percent=duty,
            actual_duty_percent=duty,
            compare_ticks=0 if duty == 0.0 else 200,
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
        self._status = self._make_status(float(duty_percent))
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


async def _wait_until(predicate, timeout_s: float = 0.7) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.001)


def test_watchdog_sample_stale_logs_timing_and_delivery_evidence() -> None:
    async def scenario() -> None:
        clock = Clock()
        bus = RuntimeEventBus()
        manual = FakeManualPwmService()
        diagnostic_log = LoadControlDiagnosticLog(utc_now=lambda: UTC)
        service = Stage4CZeroExportControllerService(
            bus,
            _config(),
            manual_pwm=manual,
            monotonic_ns=clock,
            diagnostic_log=diagnostic_log,
        )
        await service.start()
        service.configure(source_id="emonio-a", phase="A", p_deadband_w=2.0)
        await service.enable()
        ack_ns = clock.value

        clock.value = ack_ns + 250_000_000
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.BLOCKED_SAFE)

        stale = [event for event in diagnostic_log.recent() if event.event == "ZERO_EXPORT_SAFE_BLOCK"][-1]
        assert 'reason="SAMPLE_STALE"' in stale.line
        assert 'stale_trigger="WATCHDOG_DEADLINE"' in stale.line
        assert "poll_interval_s=0.1" in stale.line
        assert "freshness_limit_s=0.2" in stale.line
        assert "elapsed_since_last_accepted_sample_s=null" in stale.line
        assert "last_accepted_cycle_id=null" in stale.line
        assert f"causal_after_ack_ns={ack_ns}" in stale.line
        assert "elapsed_since_ack_s=0.25" in stale.line
        assert "settling_pending=true" in stale.line
        assert "event_bus_dropped_deliveries=0" in stale.line
        assert manual.commands == [0.0, 0.0]

        await service.disable()
        await service.close()

    asyncio.run(scenario())
