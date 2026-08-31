import csv
from dataclasses import replace
from datetime import timedelta
import json
import time

from emonio_viewer.recording.recorder import RecordingManager, SessionRecorder
from emonio_viewer.recording.trigger import (
    TriggerBlock,
    TriggerConfig,
    TriggerMeasurement,
    TriggerMode,
    TriggerOperator,
)
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity
from emonio_viewer.runtime.store import RuntimeStore


def with_cycle_and_p(sample, cycle_id, p, seconds):
    measurement = replace(sample.phase_a.measurement, p=p)
    phase_a = replace(sample.phase_a, measurement=measurement)
    return replace(
        sample,
        identity=replace(sample.identity, cycle_id=cycle_id),
        timing=replace(
            sample.timing,
            cycle_finished_utc=sample.timing.cycle_finished_utc + timedelta(seconds=seconds),
        ),
        phase_a=phase_a,
    )


def wait_until(predicate, timeout_s=1.5):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def make_manager(tmp_path, device_config, real_sample):
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    manager = RecordingManager(tmp_path, (device_config,), store, bus, "0.4.16")
    return manager, store, bus


def level_config(device_config, threshold=100.0):
    return TriggerConfig(
        device_id=device_config.id,
        block=TriggerBlock.A,
        measurement=TriggerMeasurement.P,
        operator=TriggerOperator.GT,
        threshold=threshold,
        mode=TriggerMode.LEVEL,
        recording_interval_s=device_config.poll_interval_s,
    )


def crossing_config(device_config, threshold=100.0):
    return replace(level_config(device_config, threshold), mode=TriggerMode.CROSSING)


def test_triggered_start_uses_exact_firing_sample_not_newer_store_sample(
    tmp_path, real_sample, device_config
):
    manager, store, bus = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(level_config(device_config, threshold=100.0))
    manager.arm_trigger(device_config.id)

    firing = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 1, 101.25, 1)
    newer = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 2, 999.0, 2)
    store.publish_sample(newer, connections_opened=1)

    manager.start_background()
    bus.publish(firing)
    assert wait_until(lambda: len(manager.active_recordings()) == 1)

    session_dir = manager._active[device_config.id].session_dir
    with (session_dir / "measurements.csv").open(newline="", encoding="utf-8") as handle:
        first = next(csv.DictReader(handle))
    assert first["cycle_id"] == str(firing.identity.cycle_id)
    assert first["A_p"] == repr(101.25)
    assert first["A_p"] != repr(999.0)
    manager.stop_all()


def test_triggered_session_records_exact_provenance_and_consumes_one_shot(
    tmp_path, real_sample, device_config
):
    manager, _, bus = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(level_config(device_config, threshold=100.0))
    manager.arm_trigger(device_config.id)
    firing = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 1, 101.25, 1)

    manager.start_background()
    bus.publish(firing)
    assert wait_until(lambda: len(manager.active_recordings()) == 1)

    status = manager.trigger_statuses()[0]
    assert status["state"] == "DISARMED"
    assert status["last_fired_cycle_id"] == firing.identity.cycle_id
    assert status["last_fired_utc"] == firing.timing.cycle_finished_utc.isoformat()
    assert status["last_fired_value"] == 101.25

    recorder = manager._active[device_config.id]
    metadata = json.loads((recorder.session_dir / "session.json").read_text(encoding="utf-8"))
    trigger = metadata["recording"]["trigger"]
    assert metadata["recording"]["start_source"] == "TRIGGER"
    assert trigger["mode"] == "LEVEL"
    assert trigger["block"] == "A"
    assert trigger["measurement"] == "P"
    assert trigger["operator"] == "GT"
    assert trigger["threshold"] == 100.0
    assert trigger["fired_cycle_id"] == firing.identity.cycle_id
    assert trigger["fired_utc"] == firing.timing.cycle_finished_utc.isoformat()
    assert trigger["fired_value"] == 101.25
    events = (recorder.session_dir / "events.csv").read_text(encoding="utf-8")
    assert "TRIGGER_FIRED" in events
    assert str(firing.identity.cycle_id) in events

    later = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 2, 150.0, 2)
    bus.publish(later)
    time.sleep(0.05)
    assert len(manager.active_recordings()) == 1
    assert manager.trigger_statuses()[0]["state"] == "DISARMED"
    manager.stop_all()


def test_crossing_diagnostic_event_clears_manager_continuity(
    tmp_path, real_sample, device_config
):
    manager, _, bus = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(crossing_config(device_config, threshold=100.0))
    manager.arm_trigger(device_config.id)
    base = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 1, 90.0, 1)
    candidate = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 2, 110.0, 2)

    manager.start_background()
    bus.publish(base)
    bus.publish(
        DiagnosticEvent(
            device_id=device_config.id,
            cycle_id=base.identity.cycle_id + 1,
            occurred_utc=base.timing.cycle_finished_utc,
            event="ACQUISITION_FAILURE",
            severity=Severity.ERROR,
            detail="simulated gap",
        )
    )
    bus.publish(candidate)
    time.sleep(0.05)

    assert manager.active_recordings() == ()
    state = manager._armed_triggers[device_config.id]
    assert state.previous_cycle_id == candidate.identity.cycle_id
    assert state.previous_value == 110.0
    manager.stop_all()


def test_trigger_start_failure_is_explicit_and_does_not_rearm(
    tmp_path, real_sample, device_config, monkeypatch
):
    manager, _, bus = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(level_config(device_config, threshold=100.0))
    manager.arm_trigger(device_config.id)
    firing = with_cycle_and_p(real_sample, real_sample.identity.cycle_id + 1, 101.0, 1)
    observer = bus.subscribe(maxsize=8)

    def fail_create(*args, **kwargs):
        raise OSError("simulated trigger start failure")

    monkeypatch.setattr(SessionRecorder, "create", fail_create)
    manager.start_background()
    bus.publish(firing)
    assert wait_until(lambda: len(manager.recording_failures()) == 1)

    failure = manager.recording_failures()[0]
    assert failure["state"] == "ERROR"
    assert failure["start_source"] == "TRIGGER"
    assert failure["failed_cycle_id"] == firing.identity.cycle_id
    assert failure["error_type"] == "OSError"
    assert failure["session_dir"] == ""
    assert manager.active_recordings() == ()
    assert manager.trigger_statuses()[0]["state"] == "DISARMED"

    seen = []
    while not observer.empty():
        seen.append(observer.get_nowait())
    assert any(
        isinstance(event, DiagnosticEvent) and event.event == "TRIGGERED_RECORDING_START_ERROR"
        for event in seen
    )
    bus.unsubscribe(observer)
    manager.stop_all()


def test_manual_session_metadata_remains_structurally_unchanged(
    tmp_path, real_sample, device_config
):
    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(
        tmp_path,
        real_sample,
        device_config,
        device_config.poll_interval_s,
        "0.4.16",
        started,
    )
    metadata = json.loads((recorder.session_dir / "session.json").read_text(encoding="utf-8"))
    assert metadata["recording"] == {"interval_s": device_config.poll_interval_s}
    recorder.stop(started)
