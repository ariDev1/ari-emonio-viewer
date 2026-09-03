import asyncio
from datetime import datetime, timezone
import inspect
import math

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.manual_pwm import ManualPwmState, ManualPwmStatus
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


UTC = datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class QuantizedManualPwmService:
    def __init__(self, clock: Clock, *, period_ticks: int = 653) -> None:
        self.clock = clock
        self.period_ticks = period_ticks
        self.pwm_owner: str | None = None
        self.commands: list[float] = []
        self.compare_history: list[int] = []
        self.sequence = 0
        self._status = self._make_status(0.0)

    def _make_status(self, duty: float) -> ManualPwmStatus:
        if duty == 0.0:
            compare = 0
            actual = 0.0
            state = ManualPwmState.OFF
        else:
            compare = int(math.floor(self.period_ticks * duty / 100.0 + 0.5))
            compare = min(max(compare, 1), self.period_ticks - 1)
            actual = 100.0 * compare / self.period_ticks
            state = ManualPwmState.APPLIED
        return ManualPwmStatus(
            state=state,
            node_id="ARI-LOAD-001",
            boot_id="BOOT-LIMIT-001",
            command_sequence=self.sequence,
            ack_result="APPLIED",
            rejection_reason=None,
            requested_duty_percent=float(duty),
            actual_duty_percent=actual,
            compare_ticks=compare,
            period_ticks=self.period_ticks,
            admissible=False,
        )

    def manual_pwm_status(self) -> ManualPwmStatus:
        return self._status

    def reserve_pwm_owner(self, owner: str) -> None:
        if self.pwm_owner is not None:
            raise RuntimeError("PWM_OWNER_RESERVED")
        self.pwm_owner = owner

    def release_pwm_owner(self, owner: str) -> None:
        if self.pwm_owner != owner:
            raise RuntimeError("PWM_OWNER_MISMATCH")
        self.pwm_owner = None

    async def run_reserved_pwm(self, duty_percent: float, *, owner: str) -> ManualPwmStatus:
        if self.pwm_owner != owner:
            raise RuntimeError("PWM_OWNER_MISMATCH")
        self.commands.append(float(duty_percent))
        self.sequence += 1
        self.clock.value += 100_000
        self._status = self._make_status(float(duty_percent))
        self.compare_history.append(int(self._status.compare_ticks or 0))
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


def _sample(cycle: int, p: float, *, finish_ns: int) -> MeasurementSample:
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


async def _publish_pair(
    *,
    clock: Clock,
    bus: RuntimeEventBus,
    first_cycle: int,
    p: float,
) -> None:
    ack_ns = clock.value
    clock.value = ack_ns + 50_000_000
    bus.publish(_sample(first_cycle, p, finish_ns=ack_ns + 25_000_000))
    await asyncio.sleep(0.005)
    clock.value = ack_ns + 100_000_000
    bus.publish(_sample(first_cycle + 1, p, finish_ns=ack_ns + 75_000_000))
    await asyncio.sleep(0.01)


async def _enabled_service():
    clock = Clock()
    bus = RuntimeEventBus()
    manual = QuantizedManualPwmService(clock)
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
    return clock, bus, manual, service


def test_low_authority_bracket_latches_confirmed_off_instead_of_chattering_0_to_25() -> None:
    async def scenario() -> None:
        clock, bus, manual, service = await _enabled_service()

        await _publish_pair(clock=clock, bus=bus, first_cycle=1, p=-20.0)
        await _wait_until(lambda: manual.commands == [0.0, 25.0])

        await _publish_pair(clock=clock, bus=bus, first_cycle=3, p=10.0)
        await _wait_until(lambda: manual.commands == [0.0, 25.0, 0.0])

        await _publish_pair(clock=clock, bus=bus, first_cycle=5, p=-20.0)
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.LIMIT_LOW)

        status = service.status()
        assert manual.commands == [0.0, 25.0, 0.0]
        assert status.action == "LIMIT_LOW"
        assert status.reason == "LOW_AUTHORITY_LIMIT"
        assert status.confirmed_requested_duty_percent == 0.0
        assert status.safe_confirmed is True
        assert status.upper_bracket_duty_percent == 25.0

        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_subtick_bisection_enters_resolution_limit_and_stops_ineffective_commands() -> None:
    async def scenario() -> None:
        clock, bus, manual, service = await _enabled_service()
        cycle = 1

        for _ in range(14):
            await _publish_pair(clock=clock, bus=bus, first_cycle=cycle, p=-20.0)
            cycle += 2
            if service.status().state is ZeroExportControllerState.RESOLUTION_LIMIT:
                break

        status = service.status()
        assert status.state is ZeroExportControllerState.RESOLUTION_LIMIT
        assert status.action == "RESOLUTION_LIMIT"
        assert status.reason == "PWM_RESOLUTION_LIMIT"
        assert len(manual.commands) >= 3
        assert manual.commands[-1] != manual.commands[-2]
        assert manual.compare_history[-1] == manual.compare_history[-2]

        command_count = len(manual.commands)
        await _publish_pair(clock=clock, bus=bus, first_cycle=cycle, p=-20.0)
        await _wait_until(lambda: service.status().state is ZeroExportControllerState.RESOLUTION_LIMIT)
        assert len(manual.commands) == command_count

        await service.disable()
        await service.close()

    asyncio.run(scenario())


def test_zero_export_service_accepts_shared_diagnostic_log_dependency() -> None:
    parameters = inspect.signature(Stage4CZeroExportControllerService).parameters
    assert "diagnostic_log" in parameters
