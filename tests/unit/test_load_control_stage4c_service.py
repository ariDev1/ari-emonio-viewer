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
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity


UTC = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class FakeManualPwmService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.pwm_owner: str | None = None
        self.commands: list[float] = []
        self.sequence = 10
        self.node_id: str | None = "ARI-LOAD-001"
        self.boot_id: str | None = "BOOT-1"
        self.unsupported = False
        self.reject_duty: float | None = None
        self._status = self._make_status(0.0, 0.0, self.sequence)

    def _make_status(self, duty: float, actual: float | None, sequence: int) -> ManualPwmStatus:
        if self.node_id is None or self.boot_id is None:
            return ManualPwmStatus(
                state=ManualPwmState.DISCONNECTED,
                node_id=None,
                boot_id=None,
                command_sequence=None,
                ack_result=None,
                rejection_reason=None,
                requested_duty_percent=None,
                actual_duty_percent=None,
                compare_ticks=None,
                period_ticks=None,
                admissible=False,
            )
        if self.unsupported:
            return ManualPwmStatus(
                state=ManualPwmState.UNSUPPORTED,
                node_id=self.node_id,
                boot_id=self.boot_id,
                command_sequence=None,
                ack_result=None,
                rejection_reason=None,
                requested_duty_percent=None,
                actual_duty_percent=None,
                compare_ticks=None,
                period_ticks=None,
                admissible=False,
            )
        return ManualPwmStatus(
            state=(ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED),
            node_id=self.node_id,
            boot_id=self.boot_id,
            command_sequence=sequence,
            ack_result="APPLIED",
            rejection_reason=None,
            requested_duty_percent=duty,
            actual_duty_percent=actual,
            compare_ticks=(0 if duty == 0.0 else 200),
            period_ticks=653,
            admissible=False,
        )

    def manual_pwm_status(self) -> ManualPwmStatus:
        if self.node_id is None or self.boot_id is None or self.unsupported:
            return self._make_status(0.0, None, self.sequence)
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
        self.clock.value += 100_000
        if self.reject_duty is not None and float(duty_percent) == self.reject_duty:
            self._status = ManualPwmStatus(
                state=ManualPwmState.REJECTED,
                node_id=self.node_id,
                boot_id=self.boot_id,
                command_sequence=self.sequence,
                ack_result=None,
                rejection_reason="PWM_ACK_TIMEOUT",
                requested_duty_percent=float(duty_percent),
                actual_duty_percent=None,
                compare_ticks=None,
                period_ticks=None,
                admissible=False,
            )
            self.reject_duty = None
            return self._status
        actual = 0.0 if duty_percent == 0.0 else float(duty_percent) + 0.05
        self._status = self._make_status(float(duty_percent), actual, self.sequence)
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
            DeviceConfig(
                id="emonio-b",
                name="Emonio B",
                host="192.0.2.11",
                poll_interval_s=0.1,
            ),
        ),
    )


def _block(p: float, q: float = 0.0, pf: float = 1.0) -> BlockState:
    measurement = PhaseMeasurement(
        vrms=230.0,
        irms=1.0,
        p=p,
        q=q,
        s=max(abs(p), 1.0),
        frequency=50.0,
        energy=0.0,
        pf=pf,
    )
    return BlockState(
        measurement=measurement,
        quadrant=classify_quadrant(p, q),
        flow=classify_flow(p),
        acquired_utc=UTC,
        raw=RawBlockEvidence(base_register=0, words=()),
    )


def _sample(
    cycle: int,
    p: float,
    *,
    finish_ns: int,
    source: str = "emonio-a",
    quality: SampleQuality = SampleQuality.VALID,
    q: float = 0.0,
    pf: float = 1.0,
) -> MeasurementSample:
    selected = _block(p, q, pf)
    zero = _block(0.0)
    return MeasurementSample(
        identity=MeasurementIdentity(
            schema_version=1,
            device_id=source,
            device_name=source,
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
        quality=quality,
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


async def _enabled_service():
    clock = Clock()
    bus = RuntimeEventBus()
    manual = FakeManualPwmService(clock)
    service = Stage4CZeroExportControllerService(
        bus,
        _config(),
        manual_pwm=manual,
        monotonic_ns=clock,
    )
    await service.start()
    service.configure(source_id="emonio-a", phase="A", p_deadband_w=2.0)
    status = await service.enable()
    return clock, bus, manual, service, status


def test_enable_reserves_pwm_and_establishes_acknowledged_off_baseline() -> None:
    async def scenario() -> None:
        clock, _bus, manual, service, status = await _enabled_service()
        assert manual.commands == [0.0]
        assert manual.pwm_owner == ZERO_EXPORT_PWM_OWNER
        assert status.state is ZeroExportControllerState.WAITING_FOR_SAMPLE
        assert status.safe_confirmed is True
        assert status.confirmed_requested_duty_percent == 0.0
        assert status.actuator_node_id == "ARI-LOAD-001"
        assert status.actuator_boot_id == "BOOT-1"
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_negative_p_after_one_causal_settling_cycle_commands_25_percent() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value

        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -40.0, finish_ns=ack_ns + 25_000_000, q=900.0, pf=0.25))
        await asyncio.sleep(0.01)
        assert manual.commands == [0.0]

        clock.value = ack_ns + 100_000_000
        bus.publish(_sample(2, -40.0, finish_ns=ack_ns + 75_000_000, q=-900.0, pf=-0.25))
        await _wait_until(lambda: manual.commands == [0.0, 25.0])
        assert service.status().confirmed_requested_duty_percent == 25.0
        assert service.status().measured_p_w == -40.0
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_wrong_source_is_ignored() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value
        clock.value = ack_ns + 80_000_000
        bus.publish(_sample(1, -100.0, finish_ns=ack_ns + 40_000_000, source="emonio-b"))
        await asyncio.sleep(0.02)
        assert manual.commands == [0.0]
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_invalid_sample_blocks_and_commands_one_confirmed_safe_off() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value
        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -10.0, finish_ns=ack_ns + 25_000_000, quality=SampleQuality.INVALID))
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.BLOCKED_SAFE)
        status = service.status()
        assert status.reason == "SAMPLE_INVALID"
        assert status.safe_confirmed is True
        assert manual.commands == [0.0, 0.0]
        assert manual.pwm_owner is None
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_sequence_gap_blocks_and_commands_safe_off() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value
        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -10.0, finish_ns=ack_ns + 25_000_000))
        await asyncio.sleep(0.01)
        clock.value = ack_ns + 100_000_000
        bus.publish(_sample(3, -10.0, finish_ns=ack_ns + 75_000_000))
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.BLOCKED_SAFE)
        assert service.status().reason == "SAMPLE_SEQUENCE_GAP"
        assert manual.commands == [0.0, 0.0]
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_selected_source_acquisition_failure_blocks_and_commands_safe_off() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        clock.value += 50_000_000
        bus.publish(
            DiagnosticEvent(
                device_id="emonio-a",
                cycle_id=1,
                occurred_utc=UTC,
                event="ACQUISITION_READ_FAILED",
                severity=Severity.ERROR,
                detail="test",
            )
        )
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.BLOCKED_SAFE)
        assert service.status().reason == "ACQUISITION_FAILURE"
        assert manual.commands == [0.0, 0.0]
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_actuator_boot_change_never_commands_the_new_boot_automatically() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value
        manual.boot_id = "BOOT-2"
        manual._status = manual._make_status(0.0, 0.0, manual.sequence)
        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -50.0, finish_ns=ack_ns + 25_000_000))
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.SAFE_UNCONFIRMED)
        assert service.status().reason == "ACTUATOR_BOOT_CHANGED"
        assert manual.commands == [0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())


def test_rejected_active_command_gets_one_distinct_safe_off_attempt() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        manual.reject_duty = 25.0
        ack_ns = clock.value
        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -50.0, finish_ns=ack_ns + 25_000_000))
        await asyncio.sleep(0.01)
        clock.value = ack_ns + 100_000_000
        bus.publish(_sample(2, -50.0, finish_ns=ack_ns + 75_000_000))
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.BLOCKED_SAFE)
        assert service.status().reason == "PWM_COMMAND_NOT_CONFIRMED"
        assert manual.commands == [0.0, 25.0, 0.0]
        assert service.status().safe_confirmed is True
        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_disable_from_active_duty_finishes_with_acknowledged_off_and_releases_owner() -> None:
    async def scenario() -> None:
        clock, bus, manual, service, _status = await _enabled_service()
        ack_ns = clock.value
        clock.value = ack_ns + 50_000_000
        bus.publish(_sample(1, -50.0, finish_ns=ack_ns + 25_000_000))
        await asyncio.sleep(0.01)
        clock.value = ack_ns + 100_000_000
        bus.publish(_sample(2, -50.0, finish_ns=ack_ns + 75_000_000))
        await _wait_until(lambda: manual.commands == [0.0, 25.0])

        status = await service.disable()
        assert status.state is ZeroExportControllerState.DISABLED
        assert status.safe_confirmed is True
        assert manual.commands == [0.0, 25.0, 0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())
