import asyncio
from datetime import datetime, timezone

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.manual_pwm import ManualPwmState, ManualPwmStatus
from emonio_viewer.load_control.stage3a import Stage3AError
from emonio_viewer.load_control.zero_export_service import (
    ZERO_EXPORT_PWM_OWNER,
    Stage4CZeroExportControllerService,
    ZeroExportControllerState,
)
from emonio_viewer.measurement.model import (
    AcquisitionMetadata,
    BlockState,
    DerivedTotals,
    MeasurementIdentity,
    MeasurementSample,
    PhaseMeasurement,
    RawBlockEvidence,
    SampleQuality,
    SampleTiming,
)
from emonio_viewer.measurement.quadrant import classify_flow, classify_quadrant
from emonio_viewer.runtime.events import RuntimeEventBus


UTC = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000

    def __call__(self) -> int:
        return self.value


class BlockingManualPwmService:
    """Model the real manual service while an active-duty ACK is pending."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.pwm_owner: str | None = None
        self.commands: list[float] = []
        self.sequence = 10
        self.node_id = "ARI-LOAD-001"
        self.boot_id = "BOOT-1"
        self._active = False
        self.active_command_started = asyncio.Event()
        self.allow_active_ack = asyncio.Event()
        self._status = self._applied_status(0.0, 0.0)

    def _applied_status(self, duty: float, actual: float) -> ManualPwmStatus:
        return ManualPwmStatus(
            state=(ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED),
            node_id=self.node_id,
            boot_id=self.boot_id,
            command_sequence=self.sequence,
            ack_result="APPLIED",
            rejection_reason=None,
            requested_duty_percent=duty,
            actual_duty_percent=actual,
            compare_ticks=(0 if duty == 0.0 else 200),
            period_ticks=653,
            admissible=False,
        )

    def _waiting_status(self, duty: float) -> ManualPwmStatus:
        return ManualPwmStatus(
            state=ManualPwmState.WAITING_FOR_ACK,
            node_id=self.node_id,
            boot_id=self.boot_id,
            command_sequence=self.sequence,
            ack_result=None,
            rejection_reason=None,
            requested_duty_percent=duty,
            actual_duty_percent=None,
            compare_ticks=None,
            period_ticks=None,
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
        if self._active:
            raise Stage3AError("CONTROL_COMMAND_ACTIVE")

        self._active = True
        try:
            duty = float(duty_percent)
            self.commands.append(duty)
            self.sequence += 1
            self.clock.value += 100_000

            if duty > 0.0:
                self._status = self._waiting_status(duty)
                self.active_command_started.set()
                await self.allow_active_ack.wait()

            actual = 0.0 if duty == 0.0 else duty + 0.05
            self._status = self._applied_status(duty, actual)
            return self._status
        finally:
            self._active = False


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


def _block(p: float) -> BlockState:
    measurement = PhaseMeasurement(
        vrms=230.0,
        irms=1.0,
        p=p,
        q=0.0,
        s=max(abs(p), 1.0),
        frequency=50.0,
        energy=0.0,
        pf=1.0,
    )
    return BlockState(
        measurement=measurement,
        quadrant=classify_quadrant(p, 0.0),
        flow=classify_flow(p),
        acquired_utc=UTC,
        raw=RawBlockEvidence(base_register=0, words=()),
    )


def _sample(cycle: int, p: float, finish_ns: int) -> MeasurementSample:
    selected = _block(p)
    zero = _block(0.0)
    return MeasurementSample(
        identity=MeasurementIdentity(
            schema_version=1,
            device_id="emonio-a",
            device_name="Emonio A",
            device_ip="192.0.2.10",
            firmware_version="3.0.79-release",
            transport="MODBUS_TCP",
            cycle_id=cycle,
        ),
        timing=SampleTiming(
            cycle_started_utc=UTC,
            cycle_finished_utc=UTC,
            cycle_started_monotonic_ns=finish_ns - 1_000,
            cycle_finished_monotonic_ns=finish_ns,
            cycle_span_ms=0.001,
        ),
        acquisition=AcquisitionMetadata(schedule_lag_ms=0.0),
        phase_a=selected,
        phase_b=zero,
        phase_c=zero,
        total=selected,
        quality=SampleQuality.VALID,
        warnings=(),
        derived=DerivedTotals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


async def _wait_until(predicate, timeout_s: float = 0.7) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.001)


def test_disable_waits_for_inflight_automatic_command_then_confirms_off() -> None:
    async def scenario() -> None:
        clock = Clock()
        bus = RuntimeEventBus()
        manual = BlockingManualPwmService(clock)
        service = Stage4CZeroExportControllerService(
            bus,
            _config(),
            manual_pwm=manual,
            monotonic_ns=clock,
        )
        await service.start()
        service.configure(source_id="emonio-a", phase="A", p_deadband_w=2.0)
        await service.enable()
        assert manual.commands == [0.0]
        assert manual.pwm_owner == ZERO_EXPORT_PWM_OWNER

        ack_ns = clock.value
        clock.value = ack_ns + 30_000_000
        bus.publish(_sample(1, -50.0, ack_ns + 20_000_000))
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.SETTLING)

        clock.value = ack_ns + 70_000_000
        bus.publish(_sample(2, -50.0, ack_ns + 60_000_000))
        await asyncio.wait_for(manual.active_command_started.wait(), timeout=0.7)
        assert manual.commands == [0.0, 25.0]

        disable_task = asyncio.create_task(service.disable())
        try:
            await asyncio.sleep(0.02)
            assert not disable_task.done(), "disable must serialize behind the in-flight automatic PWM command"
        finally:
            manual.allow_active_ack.set()

        status = await asyncio.wait_for(disable_task, timeout=0.7)
        assert status.state is ZeroExportControllerState.DISABLED
        assert status.safe_confirmed is True
        assert status.confirmed_requested_duty_percent == 0.0
        assert manual.commands == [0.0, 25.0, 0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())
