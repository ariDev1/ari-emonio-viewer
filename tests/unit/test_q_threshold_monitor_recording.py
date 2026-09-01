from dataclasses import replace
from datetime import timedelta
import json
import time

import emonio_viewer.recording.negative_monitor as monitor
from emonio_viewer.recording.continuous_monitor import NegativeMonitorRecordingManager
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore


def with_cycle_and_q(sample, cycle_id, q, seconds):
    measurement = replace(sample.phase_a.measurement, q=q)
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


def test_q_triggered_session_records_exact_threshold_direction_and_start_evidence(
    tmp_path, real_sample, device_config
):
    assert hasattr(monitor.NegativeCondition, "Q_THRESHOLD")
    assert hasattr(monitor, "QDirection")

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    manager = NegativeMonitorRecordingManager(
        tmp_path,
        (device_config,),
        store,
        bus,
        "0.4.19",
    )
    config = monitor.NegativeMonitorConfig(
        device_id=device_config.id,
        condition=monitor.NegativeCondition.Q_THRESHOLD,
        phases=(monitor.MonitorPhase.A,),
        recording_interval_s=device_config.poll_interval_s,
        threshold_var=100.0,
        q_direction=monitor.QDirection.POSITIVE,
    )
    manager.configure_monitor(config)
    manager.enable_monitor(device_config.id)

    baseline = with_cycle_and_q(
        real_sample,
        real_sample.identity.cycle_id + 1,
        0.0,
        1,
    )
    firing = with_cycle_and_q(
        real_sample,
        real_sample.identity.cycle_id + 2,
        101.25,
        2,
    )

    manager.start_background()
    bus.publish(baseline)
    bus.publish(firing)
    assert wait_until(lambda: len(manager.active_recordings()) == 1)

    recorder = manager._active[device_config.id]
    metadata = json.loads((recorder.session_dir / "session.json").read_text(encoding="utf-8"))
    recording = metadata["recording"]
    evidence = recording["monitor"]
    assert recording["start_source"] == "Q_THRESHOLD_MONITOR"
    assert evidence["condition"] == "Q_THRESHOLD"
    assert evidence["phases"] == ["A"]
    assert evidence["threshold_var"] == 100.0
    assert evidence["q_direction"] == "POSITIVE"
    assert evidence["start_phase"] == "A"
    assert evidence["start_measurement"] == "Q"
    assert evidence["start_event"] == "Q_THRESHOLD_START"
    assert evidence["start_cycle_id"] == firing.identity.cycle_id
    assert evidence["start_utc"] == firing.timing.cycle_finished_utc.isoformat()
    assert evidence["start_value"] == 101.25

    events = (recorder.session_dir / "events.csv").read_text(encoding="utf-8")
    assert "Q_THRESHOLD_START" in events
    assert "threshold_var=100.0" in events
    assert "q_direction=POSITIVE" in events
    manager.stop_all()
