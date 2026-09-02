import asyncio
from datetime import datetime, timezone

import pytest

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.characterization_service import (
    CHARACTERIZATION_PWM_OWNER,
    CharacterizationState,
    Stage4BCharacterizationService,
)
from emonio_viewer.load_control.manual_pwm import ManualPwmState, ManualPwmStatus
from emonio_viewer.load_control.stage3a import Stage3AError
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


UTC = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)


class FakeManualPwmService:
    def __init__(self, *, duty: float = 35.0, actual: float = 35.068913) -> None:
        self.pwm_owner: str | None = None
        self.commands: list[float] = []
        self.sequence = 100
        self.fail_off = False
        self._status = self._make_status(duty, actual, self.sequence)

    @staticmethod
    def _make_status(duty: float, actual: float, sequence: int) -> ManualPwmStatus:
        return ManualPwmStatus(
            state=(ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED),
            node_id="ARI-LOAD-001",
            boot_id="BOOT-1",
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
        if duty_percent == 0.0 and self.fail_off:
            self._status = ManualPwmStatus(
                state=ManualPwmState.REJECTED,
                node_id="ARI-LOAD-001",
                boot_id="BOOT-1",
                command_sequence=self.sequence,
                ack_result=None,
                rejection_reason="PWM_ACK_TIMEOUT",
                requested_duty_percent=0.0,
                actual_duty_percent=None,
                compare_ticks=None,
                period_ticks=None,
                admissible=False,
            )
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
        pf=(-1.0 if p < 0.0 else 1.0),
    )
    return BlockState(
        measurement=measurement,
        quadrant=classify_quadrant(p, 0.0),
        flow=classify_flow(p),
        acquired_utc=UTC,
        raw=RawBlockEvidence(base_register=0, words=()),
    )


def _sample(cycle: int, p: float, *, quality: SampleQuality = SampleQuality.VALID) -> MeasurementSample:
    phase_a = _block(p)
    phase_b = _block(1000.0 + cycle)
    phase_c = _block(0.0)
    start_ns = 1_000_000_000 + cycle * 100_000_000
    finish_ns = start_ns + 1_000_000
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
            cycle_started_monotonic_ns=start_ns,
            cycle_finished_monotonic_ns=finish_ns,
            cycle_span_ms=1.0,
        ),
        acquisition=AcquisitionMetadata(schedule_lag_ms=0.0),
        phase_a=phase_a,
        phase_b=phase_b,
        phase_c=phase_c,
        total=phase_a,
        quality=quality,
        warnings=(),
        derived=DerivedTotals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


async def _wait_until(predicate, timeout_s: float = 0.5) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.001)


def test_manual_capture_uses_two_settling_and_three_measured_cycles_then_off() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        manual = FakeManualPwmService(duty=35.0, actual=35.068913)
        service = Stage4BCharacterizationService(bus, _config(), manual_pwm=manual)
        await service.start()

        request = asyncio.create_task(service.capture_manual(source_id="emonio-a", phase="A"))
        await _wait_until(lambda: manual.pwm_owner == CHARACTERIZATION_PWM_OWNER)
        for cycle, p in enumerate((-20.0, -15.0, -7.4, -6.8, -7.1), start=1):
            bus.publish(_sample(cycle, p))
            await asyncio.sleep(0.005)

        status = await request
        assert status.state is CharacterizationState.COMPLETED
        assert status.safe_confirmed is True
        assert status.last_error is None
        assert len(status.points) == 1
        point = status.points[0]
        assert point.requested_duty_percent == 35.0
        assert point.actual_duty_percent == 35.068913
        assert point.cycle_ids == (3, 4, 5)
        assert point.p_samples_w == (-7.4, -6.8, -7.1)
        assert point.mean_p_w == pytest.approx(-7.1)
        assert manual.commands == [0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())


def test_auto_sweep_commands_each_explicit_point_once_and_finishes_off() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        manual = FakeManualPwmService(duty=0.0, actual=0.0)
        service = Stage4BCharacterizationService(bus, _config(), manual_pwm=manual)
        await service.start()

        request = asyncio.create_task(
            service.run_auto_sweep(source_id="emonio-a", phase="A", duties=(25.0, 35.0))
        )
        await _wait_until(lambda: manual.commands == [25.0])
        for cycle, p in enumerate((-40.0, -35.0, -30.0, -29.0, -31.0), start=1):
            bus.publish(_sample(cycle, p))
            await asyncio.sleep(0.005)

        await _wait_until(lambda: manual.commands == [25.0, 35.0])
        for cycle, p in enumerate((-20.0, -18.0, -10.0, -9.0, -11.0), start=6):
            bus.publish(_sample(cycle, p))
            await asyncio.sleep(0.005)

        status = await request
        assert status.state is CharacterizationState.COMPLETED
        assert status.safe_confirmed is True
        assert [point.requested_duty_percent for point in status.points] == [25.0, 35.0]
        assert status.points[0].cycle_ids == (3, 4, 5)
        assert status.points[1].cycle_ids == (8, 9, 10)
        assert manual.commands == [25.0, 35.0, 0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())


def test_invalid_sample_aborts_and_still_commands_acknowledged_off() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        manual = FakeManualPwmService(duty=0.0, actual=0.0)
        service = Stage4BCharacterizationService(bus, _config(), manual_pwm=manual)
        await service.start()

        request = asyncio.create_task(
            service.run_auto_sweep(source_id="emonio-a", phase="A", duties=(25.0, 35.0))
        )
        await _wait_until(lambda: manual.commands == [25.0])
        bus.publish(_sample(1, -10.0))
        await asyncio.sleep(0.005)
        bus.publish(_sample(2, -9.0, quality=SampleQuality.INVALID))

        status = await request
        assert status.state is CharacterizationState.ABORTED
        assert status.last_error == "SAMPLE_INVALID"
        assert status.safe_confirmed is True
        assert status.points == ()
        assert manual.commands == [25.0, 0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())


def test_off_ack_failure_is_reported_as_safe_unconfirmed() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        manual = FakeManualPwmService(duty=35.0, actual=35.068913)
        manual.fail_off = True
        service = Stage4BCharacterizationService(bus, _config(), manual_pwm=manual)
        await service.start()

        request = asyncio.create_task(service.capture_manual(source_id="emonio-a", phase="A"))
        await _wait_until(lambda: manual.pwm_owner == CHARACTERIZATION_PWM_OWNER)
        for cycle, p in enumerate((-20.0, -15.0, -7.4, -6.8, -7.1), start=1):
            bus.publish(_sample(cycle, p))
            await asyncio.sleep(0.005)

        status = await request
        assert status.state is CharacterizationState.SAFE_UNCONFIRMED
        assert status.safe_confirmed is False
        assert status.last_error == "SAFE_OFF_UNCONFIRMED"
        assert manual.commands == [0.0]
        assert manual.pwm_owner is None
        await service.close()

    asyncio.run(scenario())
