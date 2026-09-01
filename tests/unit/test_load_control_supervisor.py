from dataclasses import replace
from datetime import datetime, timezone

import pytest

from emonio_viewer.load_control.model import (
    ControlMode,
    LoadControlTiming,
    PersistentLoadControlConfig,
    SafeState,
    SessionState,
    ThreePhasePower,
)
from emonio_viewer.load_control.protocol import AckFrame, HelloFrame
from emonio_viewer.load_control.supervisor import EnableRejected, LoadControlSupervisor
from emonio_viewer.measurement.model import SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, Severity


NOW = datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc)


def config():
    return PersistentLoadControlConfig(
        bound_emonio_device_id="emonio-example",
        bound_actuator_node_id="ARI-LOAD-MOCK-001",
        p_reserve=30.0,
        operator_limit_a=600.0,
        operator_limit_b=600.0,
        operator_limit_c=600.0,
    )


def hello(boot_id="MOCK-BOOT-001"):
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-MOCK-001",
        boot_id=boot_id,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def sample_with(real_sample, *, cycle_id, p, quality=SampleQuality.VALID, finished_ns=None):
    finished_ns = finished_ns if finished_ns is not None else cycle_id * 1_000_000_000
    timing = replace(
        real_sample.timing,
        cycle_started_monotonic_ns=finished_ns - 100_000_000,
        cycle_finished_monotonic_ns=finished_ns,
        cycle_finished_utc=NOW,
    )
    return replace(
        real_sample,
        identity=replace(real_sample.identity, cycle_id=cycle_id),
        timing=timing,
        phase_a=replace(real_sample.phase_a, measurement=replace(real_sample.phase_a.measurement, p=p.a)),
        phase_b=replace(real_sample.phase_b, measurement=replace(real_sample.phase_b.measurement, p=p.b)),
        phase_c=replace(real_sample.phase_c, measurement=replace(real_sample.phase_c.measurement, p=p.c)),
        quality=quality,
    )


def make_supervisor():
    return LoadControlSupervisor(
        config(),
        LoadControlTiming(control_sample_max_age_s=1.0, ack_timeout_s=0.5),
        viewer_session_id="VIEWER-TEST-001",
    )


def confirm_initial_safe(supervisor, sample):
    supervisor.qualify_session(hello(), now_monotonic_ns=sample.timing.cycle_finished_monotonic_ns)
    decision = supervisor.observe_sample(
        sample,
        now_monotonic_ns=sample.timing.cycle_finished_monotonic_ns + 10_000_000,
        now_utc=NOW,
    )
    assert decision.command is not None
    assert decision.command.control_enabled is False
    assert decision.command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0)
    ack = AckFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-TEST-001",
        node_id="ARI-LOAD-MOCK-001",
        boot_id="MOCK-BOOT-001",
        sequence=decision.command.sequence,
        ack_utc=NOW.isoformat(),
        applied_p=ThreePhasePower(0.0, 0.0, 0.0),
        result="APPLIED",
    )
    supervisor.accept_ack(ack, now_monotonic_ns=sample.timing.cycle_finished_monotonic_ns + 20_000_000)


def test_enable_requires_safe_confirmed_and_current_valid_sample(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=10, p=ThreePhasePower(0.0, 0.0, 0.0))
    supervisor.qualify_session(hello(), now_monotonic_ns=10_000_000_000)
    supervisor.observe_sample(first, now_monotonic_ns=10_010_000_000, now_utc=NOW)
    with pytest.raises(EnableRejected, match="SAFE_NOT_CONFIRMED"):
        supervisor.enable(evidence_healthy=True, now_monotonic_ns=10_020_000_000)

    safe = supervisor.outstanding_command
    supervisor.accept_ack(
        AckFrame(1, "VIEWER-TEST-001", "ARI-LOAD-MOCK-001", "MOCK-BOOT-001", safe.sequence, NOW.isoformat(), ThreePhasePower(0.0, 0.0, 0.0), "APPLIED"),
        now_monotonic_ns=10_030_000_000,
    )
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=10_040_000_000)
    assert supervisor.control_mode is ControlMode.ENABLED
    assert supervisor.safe_state is SafeState.NOT_REQUIRED


def test_enabled_next_sample_generates_independent_phase_command(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=10, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=10_030_000_000)

    next_sample = sample_with(real_sample, cycle_id=11, p=ThreePhasePower(-420.0, 25.0, 100.0))
    decision = supervisor.observe_sample(next_sample, now_monotonic_ns=11_010_000_000, now_utc=NOW)
    assert decision.command is not None
    assert decision.command.control_enabled is True
    assert decision.command.p_load_request == ThreePhasePower(450.0, 5.0, 0.0)
    assert decision.command.q_comp_request == ThreePhasePower(0.0, 0.0, 0.0)


def test_intermediate_samples_are_observed_but_not_replayed_after_ack(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=20, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=20_030_000_000)
    command = supervisor.observe_sample(
        sample_with(real_sample, cycle_id=21, p=ThreePhasePower(-100.0, 0.0, 0.0)),
        now_monotonic_ns=21_010_000_000,
        now_utc=NOW,
    ).command
    assert command is not None
    assert supervisor.observe_sample(
        sample_with(real_sample, cycle_id=22, p=ThreePhasePower(-200.0, 0.0, 0.0)),
        now_monotonic_ns=22_010_000_000,
        now_utc=NOW,
    ).command is None
    supervisor.accept_ack(
        AckFrame(1, "VIEWER-TEST-001", "ARI-LOAD-MOCK-001", "MOCK-BOOT-001", command.sequence, NOW.isoformat(), command.p_load_request, "APPLIED"),
        now_monotonic_ns=22_020_000_000,
    )
    assert supervisor.observe_sample(
        sample_with(real_sample, cycle_id=23, p=ThreePhasePower(-50.0, 0.0, 0.0)),
        now_monotonic_ns=23_010_000_000,
        now_utc=NOW,
    ).command is not None


def test_source_cycle_gap_trips_and_preempts_with_safe_command(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=30, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=30_030_000_000)
    supervisor.observe_sample(sample_with(real_sample, cycle_id=31, p=ThreePhasePower(-100.0, 0.0, 0.0)), now_monotonic_ns=31_010_000_000, now_utc=NOW)
    decision = supervisor.observe_sample(sample_with(real_sample, cycle_id=33, p=ThreePhasePower(-100.0, 0.0, 0.0)), now_monotonic_ns=33_010_000_000, now_utc=NOW)
    assert supervisor.control_mode is ControlMode.TRIPPED
    assert supervisor.trip_reason == "CONTROL_SAMPLE_SEQUENCE_GAP"
    assert decision.command is not None
    assert decision.command.control_enabled is False
    assert decision.command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0)


def test_stale_sample_and_bound_source_diagnostic_trip(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=40, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=40_030_000_000)
    stale = sample_with(real_sample, cycle_id=41, p=ThreePhasePower(-10.0, 0.0, 0.0))
    supervisor.observe_sample(stale, now_monotonic_ns=42_100_000_000, now_utc=NOW)
    assert supervisor.control_mode is ControlMode.TRIPPED
    assert supervisor.trip_reason == "CONTROL_SAMPLE_STALE"

    second = make_supervisor()
    initial = sample_with(real_sample, cycle_id=50, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(second, initial)
    second.enable(evidence_healthy=True, now_monotonic_ns=50_030_000_000)
    decision = second.observe_diagnostic(
        DiagnosticEvent("emonio-example", 51, NOW, "ACQUISITION_TIMEOUT", Severity.ERROR, "timeout"),
        now_utc=NOW,
    )
    assert second.control_mode is ControlMode.TRIPPED
    assert second.trip_reason == "ACQUISITION_FAILURE"
    assert decision.command is not None


def test_other_emonio_never_drives_control(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=60, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=60_030_000_000)
    other = replace(
        sample_with(real_sample, cycle_id=1, p=ThreePhasePower(-500.0, -500.0, -500.0)),
        identity=replace(real_sample.identity, device_id="other-emonio", cycle_id=1),
    )
    assert supervisor.observe_sample(other, now_monotonic_ns=1_010_000_000, now_utc=NOW).command is None
    assert supervisor.last_source_cycle_id == 60


def test_wrong_ack_sequence_trips_and_old_ack_cannot_restore_state(real_sample):
    supervisor = make_supervisor()
    first = sample_with(real_sample, cycle_id=70, p=ThreePhasePower(0.0, 0.0, 0.0))
    confirm_initial_safe(supervisor, first)
    supervisor.enable(evidence_healthy=True, now_monotonic_ns=70_030_000_000)
    normal = supervisor.observe_sample(sample_with(real_sample, cycle_id=71, p=ThreePhasePower(-100.0, 0.0, 0.0)), now_monotonic_ns=71_010_000_000, now_utc=NOW).command
    bad = AckFrame(1, "VIEWER-TEST-001", "ARI-LOAD-MOCK-001", "MOCK-BOOT-001", normal.sequence + 1, NOW.isoformat(), normal.p_load_request, "APPLIED")
    decision = supervisor.accept_ack(bad, now_monotonic_ns=71_020_000_000)
    assert supervisor.control_mode is ControlMode.TRIPPED
    assert supervisor.trip_reason == "ACK_INVALID"
    assert decision.command is not None
    assert decision.command.sequence > normal.sequence

    late = AckFrame(1, "VIEWER-TEST-001", "ARI-LOAD-MOCK-001", "MOCK-BOOT-001", normal.sequence, NOW.isoformat(), normal.p_load_request, "APPLIED")
    supervisor.accept_ack(late, now_monotonic_ns=71_030_000_000)
    assert supervisor.control_mode is ControlMode.TRIPPED
    assert supervisor.acknowledged_p == ThreePhasePower(0.0, 0.0, 0.0)
