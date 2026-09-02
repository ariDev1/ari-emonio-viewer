import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import math

import pytest

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.automatic_observation import (
    PControlDecision,
    PControlObserverError,
    PControlObserverService,
    PControlObserverState,
    calculate_p_control_proposal,
)
from emonio_viewer.load_control.manual_pwm import (
    ManualPwmState,
    ManualPwmStatus,
    PWM_DUTY_CONTROL_CAPABILITY,
)
from emonio_viewer.load_control.qualification import QualificationState, QualificationStatus
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


UTC = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class Providers:
    def __init__(self) -> None:
        self.qualification = _qualification()
        self.manual = _manual()

    def qualification_status(self) -> QualificationStatus:
        return self.qualification

    def manual_pwm_status(self) -> ManualPwmStatus | None:
        return self.manual


def _config(*, poll_interval_s: float = 0.1) -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-a"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(
            DeviceConfig(
                id="emonio-a",
                name="Emonio A",
                host="192.0.2.10",
                poll_interval_s=poll_interval_s,
            ),
            DeviceConfig(
                id="emonio-b",
                name="Emonio B",
                host="192.0.2.11",
                poll_interval_s=poll_interval_s,
            ),
        ),
    )


def _qualification(
    *,
    connected: bool = True,
    hello_qualified: bool = True,
    boot_id: str = "BOOT-1",
    capabilities: tuple[str, ...] = ("ACTIVE_LOAD_CONTROL", PWM_DUTY_CONTROL_CAPABILITY),
) -> QualificationStatus:
    return QualificationStatus(
        state=(QualificationState.QUALIFIED if hello_qualified else QualificationState.DISCONNECTED),
        connected=connected,
        hello_qualified=hello_qualified,
        selected_node_id="ARI-LOAD-001",
        node_id=("ARI-LOAD-001" if hello_qualified else None),
        boot_id=(boot_id if hello_qualified else None),
        protocol_version=(1 if hello_qualified else None),
        device_class=("ARI_LOAD_ACTUATOR" if hello_qualified else None),
        capabilities=(capabilities if hello_qualified else ()),
        p_max=None,
        location=None,
        last_error=None,
    )


def _manual(
    *,
    duty: float | None = 25.0,
    actual: float | None = 24.96171516,
    sequence: int | None = 10,
    boot_id: str = "BOOT-1",
    ack_result: str | None = "APPLIED",
) -> ManualPwmStatus:
    state = ManualPwmState.OFF if duty == 0.0 else ManualPwmState.APPLIED
    return ManualPwmStatus(
        state=state,
        node_id="ARI-LOAD-001",
        boot_id=boot_id,
        command_sequence=sequence,
        ack_result=ack_result,
        rejection_reason=None,
        requested_duty_percent=duty,
        actual_duty_percent=actual,
        compare_ticks=(0 if duty == 0.0 else 163),
        period_ticks=653,
        admissible=True,
    )


def _block(p: float, q: float, pf: float) -> BlockState:
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
    *,
    cycle: int,
    p: float = -60.0,
    q: float = 0.0,
    pf: float = -1.0,
    source: str = "emonio-a",
    quality: SampleQuality = SampleQuality.VALID,
    start_ns: int = 1_000_000_100,
    finish_ns: int = 1_000_000_200,
) -> MeasurementSample:
    selected = _block(p, q, pf)
    zero = _block(0.0, 0.0, 1.0)
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
            cycle_started_monotonic_ns=start_ns,
            cycle_finished_monotonic_ns=finish_ns,
            cycle_span_ms=(finish_ns - start_ns) / 1_000_000.0,
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


async def _wait_until(predicate, *, timeout_s: float = 0.5) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.005)


def _configured_service(
    *,
    clock: Clock | None = None,
    providers: Providers | None = None,
    poll_interval_s: float = 0.1,
) -> tuple[PControlObserverService, RuntimeEventBus, Clock, Providers]:
    bus = RuntimeEventBus()
    clock = clock or Clock()
    providers = providers or Providers()
    service = PControlObserverService(
        bus,
        _config(poll_interval_s=poll_interval_s),
        qualification_status=providers.qualification_status,
        manual_pwm_status=providers.manual_pwm_status,
        monotonic_ns=clock,
    )
    service.configure(
        source_id="emonio-a",
        phase="A",
        p_target_w=0.0,
        p_deadband_w=2.0,
        duty_step_percent=5.0,
    )
    return service, bus, clock, providers


def test_increase_from_off_starts_at_25_percent() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-60.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 25.0
    assert result.low_w == -2.0
    assert result.high_w == 2.0


def test_increase_uses_one_step() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-15.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 30.0


def test_target_band_holds_confirmed_duty() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-1.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=40.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.HOLD
    assert result.proposed_duty_percent == 40.0


def test_decrease_from_25_percent_proposes_off() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=5.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.DECREASE
    assert result.proposed_duty_percent == 0.0


def test_confirmed_75_percent_is_high_limit() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=75.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_HIGH
    assert result.proposed_duty_percent == 75.0


def test_confirmed_off_is_low_limit_when_less_load_is_required() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_LOW
    assert result.proposed_duty_percent == 0.0


def test_reaching_75_percent_from_below_is_still_increase() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=70.0,
        duty_step_percent=10.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 75.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measured_p_w", math.nan),
        ("p_target_w", math.inf),
        ("p_deadband_w", -math.inf),
        ("confirmed_duty_percent", math.nan),
        ("duty_step_percent", math.inf),
    ],
)
def test_non_finite_inputs_are_rejected(field: str, value: float) -> None:
    kwargs = {
        "measured_p_w": -10.0,
        "p_target_w": 0.0,
        "p_deadband_w": 2.0,
        "confirmed_duty_percent": 25.0,
        "duty_step_percent": 5.0,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        calculate_p_control_proposal(**kwargs)


def test_negative_deadband_is_rejected() -> None:
    with pytest.raises(ValueError, match="p_deadband_w"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=-0.1,
            confirmed_duty_percent=25.0,
            duty_step_percent=5.0,
        )


@pytest.mark.parametrize("step", [0.0, -0.1])
def test_non_positive_step_is_rejected(step: float) -> None:
    with pytest.raises(ValueError, match="duty_step_percent"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=2.0,
            confirmed_duty_percent=25.0,
            duty_step_percent=step,
        )


@pytest.mark.parametrize("duty", [0.1, 24.999, 75.001, 90.0])
def test_unqualified_confirmed_duty_is_rejected(duty: float) -> None:
    with pytest.raises(ValueError, match="confirmed_duty_percent"):
        calculate_p_control_proposal(
            measured_p_w=-10.0,
            p_target_w=0.0,
            p_deadband_w=2.0,
            confirmed_duty_percent=duty,
            duty_step_percent=5.0,
        )


def test_configuration_is_atomic_and_rejected_while_active() -> None:
    async def scenario() -> None:
        service, _bus, _clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        with pytest.raises(PControlObserverError, match="OBSERVER_NOT_DISABLED"):
            service.configure(
                source_id="emonio-a",
                phase="B",
                p_target_w=0.0,
                p_deadband_w=1.0,
                duty_step_percent=2.0,
            )
        status = service.status()
        assert status.phase == "A"
        assert status.p_deadband_w == 2.0
        assert status.duty_step_percent == 5.0
        await service.close()

    asyncio.run(scenario())


def test_invalid_configuration_does_not_partially_mutate_settings() -> None:
    service, _bus, _clock, _providers = _configured_service()
    before = service.status()
    with pytest.raises(PControlObserverError, match="PARAMETER_INVALID"):
        service.configure(
            source_id="emonio-a",
            phase="B",
            p_target_w=1.0,
            p_deadband_w=-1.0,
            duty_step_percent=10.0,
        )
    after = service.status()
    assert after.source_id == before.source_id
    assert after.phase == before.phase
    assert after.p_target_w == before.p_target_w
    assert after.p_deadband_w == before.p_deadband_w
    assert after.duty_step_percent == before.duty_step_percent


def test_enable_rejects_missing_confirmed_pwm_ack() -> None:
    async def scenario() -> None:
        providers = Providers()
        providers.manual = _manual(duty=None, actual=None, sequence=None, ack_result=None)
        service, _bus, _clock, _providers = _configured_service(providers=providers)
        await service.start()
        with pytest.raises(PControlObserverError, match="CONFIRMED_DUTY_UNKNOWN"):
            await service.enable()
        assert service.status().state is PControlObserverState.DISABLED
        assert service.status().proposed_duty_percent is None
        await service.close()

    asyncio.run(scenario())


def test_enable_rejects_unqualified_or_unsupported_actuator() -> None:
    async def scenario() -> None:
        providers = Providers()
        providers.qualification = _qualification(connected=False, hello_qualified=False)
        service, _bus, _clock, _providers = _configured_service(providers=providers)
        await service.start()
        with pytest.raises(PControlObserverError, match="ACTUATOR_NOT_QUALIFIED"):
            await service.enable()
        providers.qualification = _qualification(capabilities=("ACTIVE_LOAD_CONTROL",))
        with pytest.raises(PControlObserverError, match="PWM_DUTY_CONTROL_NOT_SUPPORTED"):
            await service.enable()
        await service.close()

    asyncio.run(scenario())


def test_canonical_p_is_used_and_q_pf_do_not_change_proposal() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1, p=-60.0, q=10.0, pf=-0.5))
        await _wait_until(lambda: service.status().sample_cycle_id == 1)
        first = service.status()
        assert first.measured_p_w == -60.0
        assert first.decision is PControlDecision.INCREASE
        assert first.proposed_duty_percent == 30.0

        clock.value = 1_100_000_300
        bus.publish(
            _sample(
                cycle=2,
                p=-60.0,
                q=-999.0,
                pf=0.99,
                start_ns=1_100_000_100,
                finish_ns=1_100_000_200,
            )
        )
        await _wait_until(lambda: service.status().sample_cycle_id == 2)
        second = service.status()
        assert second.measured_q_var == -999.0
        assert second.proposed_duty_percent == first.proposed_duty_percent
        assert second.decision is first.decision
        await service.close()

    asyncio.run(scenario())


def test_wrong_source_is_ignored_without_changing_state() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1, source="emonio-b"))
        await asyncio.sleep(0.08)
        status = service.status()
        assert status.state is PControlObserverState.WAITING_FOR_SAMPLE
        assert status.sample_cycle_id is None
        assert status.proposed_duty_percent is None
        await service.close()

    asyncio.run(scenario())


def test_unapplied_proposals_do_not_accumulate() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1))
        await _wait_until(lambda: service.status().sample_cycle_id == 1)
        assert service.status().proposed_duty_percent == 30.0
        clock.value = 1_100_000_300
        bus.publish(
            _sample(
                cycle=2,
                start_ns=1_100_000_100,
                finish_ns=1_100_000_200,
            )
        )
        await _wait_until(lambda: service.status().sample_cycle_id == 2)
        assert service.status().proposed_duty_percent == 30.0
        await service.close()

    asyncio.run(scenario())


def test_invalid_quality_blocks_and_block_is_latched() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1, quality=SampleQuality.INVALID))
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == "SAMPLE_NOT_VALID"
        assert service.status().proposed_duty_percent is None

        clock.value = 1_100_000_300
        bus.publish(
            _sample(
                cycle=2,
                start_ns=1_100_000_100,
                finish_ns=1_100_000_200,
            )
        )
        await asyncio.sleep(0.08)
        assert service.status().state is PControlObserverState.BLOCKED
        await service.disable()
        assert service.status().state is PControlObserverState.DISABLED
        await service.close()

    asyncio.run(scenario())


def test_stale_sample_blocks() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service(poll_interval_s=0.1)
        await service.start()
        await service.enable()
        clock.value = 2_000_000_000
        bus.publish(_sample(cycle=1, start_ns=1_000_000_000, finish_ns=1_100_000_000))
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == "SAMPLE_STALE"
        await service.close()

    asyncio.run(scenario())


def test_missing_expected_sample_blocks_on_freshness_deadline() -> None:
    async def scenario() -> None:
        service, _bus, clock, _providers = _configured_service(poll_interval_s=0.05)
        await service.start()
        await service.enable()
        clock.value += 200_000_000
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == "SAMPLE_STALE"
        await service.close()

    asyncio.run(scenario())


def test_sequence_gap_blocks_after_valid_cycle() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1))
        await _wait_until(lambda: service.status().sample_cycle_id == 1)
        clock.value = 1_100_000_300
        bus.publish(
            _sample(
                cycle=3,
                start_ns=1_100_000_100,
                finish_ns=1_100_000_200,
            )
        )
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == "SAMPLE_SEQUENCE_GAP"
        await service.close()

    asyncio.run(scenario())


def test_acquisition_failure_blocks_selected_source() -> None:
    async def scenario() -> None:
        service, bus, _clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        bus.publish(
            DiagnosticEvent(
                device_id="emonio-a",
                cycle_id=1,
                occurred_utc=UTC,
                event="ACQUISITION_TIMEOUT",
                severity=Severity.ERROR,
                detail="timeout",
            )
        )
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == "ACQUISITION_FAILURE"
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("disconnect", "ACTUATOR_DISCONNECTED"),
        ("boot", "ACTUATOR_BOOT_CHANGED"),
        ("capability", "PWM_DUTY_CONTROL_NOT_SUPPORTED"),
        ("unknown", "CONFIRMED_DUTY_UNKNOWN"),
        ("outside", "CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW"),
    ],
)
def test_runtime_actuator_evidence_failures_block(mutation: str, reason: str) -> None:
    async def scenario() -> None:
        providers = Providers()
        service, bus, clock, _providers = _configured_service(providers=providers)
        await service.start()
        await service.enable()
        if mutation == "disconnect":
            providers.qualification = _qualification(connected=False, hello_qualified=False)
        elif mutation == "boot":
            providers.qualification = _qualification(boot_id="BOOT-2")
            providers.manual = _manual(boot_id="BOOT-2", duty=None, actual=None, sequence=None, ack_result=None)
        elif mutation == "capability":
            providers.qualification = _qualification(capabilities=("ACTIVE_LOAD_CONTROL",))
        elif mutation == "unknown":
            providers.manual = _manual(duty=None, actual=None, sequence=None, ack_result=None)
        elif mutation == "outside":
            providers.manual = _manual(duty=10.0, actual=10.0, sequence=11)
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1))
        await _wait_until(lambda: service.status().state is PControlObserverState.BLOCKED)
        assert service.status().reason == reason
        assert service.status().proposed_duty_percent is None
        await service.close()

    asyncio.run(scenario())


def test_changed_manual_ack_creates_causal_measurement_boundary() -> None:
    async def scenario() -> None:
        providers = Providers()
        service, bus, clock, _providers = _configured_service(providers=providers)
        await service.start()
        await service.enable()

        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1))
        await _wait_until(lambda: service.status().sample_cycle_id == 1)
        assert service.status().proposed_duty_percent == 30.0

        providers.manual = _manual(duty=30.0, actual=29.9, sequence=11)
        clock.value = 1_100_000_300
        bus.publish(
            _sample(
                cycle=2,
                start_ns=1_100_000_100,
                finish_ns=1_100_000_200,
            )
        )
        await _wait_until(lambda: service.status().state is PControlObserverState.WAITING_FOR_SAMPLE)
        assert service.status().sample_cycle_id == 2
        assert service.status().proposed_duty_percent is None

        clock.value = 1_200_000_300
        bus.publish(
            _sample(
                cycle=3,
                start_ns=1_200_000_100,
                finish_ns=1_200_000_200,
            )
        )
        await _wait_until(lambda: service.status().sample_cycle_id == 3)
        assert service.status().state is PControlObserverState.OBSERVING
        assert service.status().confirmed_requested_duty_percent == 30.0
        assert service.status().proposed_duty_percent == 35.0
        await service.close()

    asyncio.run(scenario())


def test_one_sample_produces_one_proposal_diagnostic() -> None:
    async def scenario() -> None:
        service, bus, clock, _providers = _configured_service()
        await service.start()
        await service.enable()
        clock.value = 1_000_000_300
        bus.publish(_sample(cycle=1))
        await _wait_until(lambda: service.status().sample_cycle_id == 1)
        events = [event for event in service.diagnostics() if event.event == "P_OBSERVER_PROPOSAL_CALCULATED"]
        assert len(events) == 1
        await service.close()

    asyncio.run(scenario())
