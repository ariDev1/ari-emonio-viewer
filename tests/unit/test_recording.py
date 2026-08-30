import csv
from dataclasses import replace
from datetime import timedelta

import pytest

from emonio_viewer.recording.csv_writer import sample_to_csv_row
from emonio_viewer.recording.recorder import RecordingManager, SessionRecorder
from emonio_viewer.recording.session import discover_resumable_session


def read_measurement_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def with_finish_time(sample, when):
    return replace(sample, timing=replace(sample.timing, cycle_finished_utc=when))


def test_measurement_csv_preserves_sign_and_round_trip_measurement_evidence(tmp_path, real_sample, device_config) -> None:
    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(tmp_path, real_sample, device_config, 10.0, "0.1.1", started)
    recorder.stop(started)
    row = read_measurement_rows(recorder.session_dir / "measurements.csv")[0]
    assert row["B_p"] == repr(real_sample.phase_b.measurement.p)
    assert row["B_q"] == repr(real_sample.phase_b.measurement.q)
    assert row["B_pf"] == repr(real_sample.phase_b.measurement.pf)
    assert row["B_kwh"] == repr(real_sample.phase_b.measurement.energy)
    assert float(row["B_p"]) == real_sample.phase_b.measurement.p
    assert float(row["B_q"]) == real_sample.phase_b.measurement.q
    assert float(row["B_pf"]) == real_sample.phase_b.measurement.pf
    assert float(row["B_kwh"]) == real_sample.phase_b.measurement.energy
    assert row["B_p"].startswith("-")
    assert row["B_q"].startswith("-")
    assert row["B_pf"].startswith("-")
    assert row["B_kwh"].startswith("-")


def test_first_valid_sample_after_record_deadline_is_used(tmp_path, real_sample, device_config) -> None:
    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(tmp_path, real_sample, device_config, 10.0, "0.1.0", started)
    recorder.consider_sample(with_finish_time(real_sample, started + timedelta(seconds=8)))
    recorder.consider_sample(with_finish_time(real_sample, started + timedelta(seconds=10, milliseconds=200)))
    recorder.stop(started + timedelta(seconds=11))
    rows = read_measurement_rows(recorder.session_dir / "measurements.csv")
    assert len(rows) == 2


def test_gap_is_event_not_zero_or_repeated_measurement(tmp_path, real_sample, device_config) -> None:
    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(tmp_path, real_sample, device_config, 10.0, "0.1.0", started)
    recorder.consider_sample(with_finish_time(real_sample, started))
    recorder.consider_sample(with_finish_time(real_sample, started + timedelta(seconds=21)))
    recorder.stop(started + timedelta(seconds=22))
    rows = read_measurement_rows(recorder.session_dir / "measurements.csv")
    events = (recorder.session_dir / "events.csv").read_text(encoding="utf-8")
    assert len(rows) == 2
    assert "RECORD_POINT_MISSED" in events


def test_existing_session_directory_is_not_overwritten(tmp_path, real_sample, device_config) -> None:
    started = real_sample.timing.cycle_finished_utc
    first = SessionRecorder.create(tmp_path, real_sample, device_config, 10.0, "0.1.0", started)
    with pytest.raises(FileExistsError):
        SessionRecorder.create(tmp_path, real_sample, device_config, 10.0, "0.1.0", started)
    first.stop(started)


def test_unclean_previous_directory_is_not_resumed(tmp_path) -> None:
    prior = tmp_path / "2026-08-27T160000Z_emonio-example"
    prior.mkdir()
    (prior / "session.json").write_text('{"started_utc":"2026-08-27T16:00:00Z"}', encoding="utf-8")
    assert discover_resumable_session(tmp_path) is None


def test_recording_interval_cannot_be_faster_than_acquisition(tmp_path, real_sample, device_config) -> None:
    device = replace(device_config, poll_interval_s=2.0)
    started = real_sample.timing.cycle_finished_utc
    with pytest.raises(ValueError, match="recording interval.*acquisition interval"):
        SessionRecorder.create(tmp_path, real_sample, device, 1.0, "0.1.1", started)


@pytest.mark.parametrize("interval_s", (float("nan"), float("inf"), float("-inf")))
def test_recording_interval_rejects_non_finite_value(
    tmp_path, real_sample, device_config, interval_s
) -> None:
    started = real_sample.timing.cycle_finished_utc
    with pytest.raises(ValueError, match="recording interval must be finite"):
        SessionRecorder.create(
            tmp_path, real_sample, device_config, interval_s, "0.4.9", started
        )


def test_active_recording_cannot_be_changed_below_acquisition_interval(tmp_path, real_sample, device_config) -> None:
    device = replace(device_config, poll_interval_s=2.0)
    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(tmp_path, real_sample, device, 2.0, "0.1.1", started)
    with pytest.raises(ValueError, match="recording interval.*acquisition interval"):
        recorder.set_interval(1.0, started + timedelta(seconds=1))
    recorder.stop(started + timedelta(seconds=1))


def test_csv_measurement_values_preserve_small_nonzero_values_without_four_decimal_truncation(real_sample) -> None:
    p = 0.000043
    measurement = replace(real_sample.phase_b.measurement, p=p)
    block = replace(real_sample.phase_b, measurement=measurement)
    sample = replace(real_sample, phase_b=block)
    row = sample_to_csv_row(sample, sample.timing.cycle_finished_utc.isoformat(), 0.0)

    assert row["B_p"] == repr(p)
    assert float(row["B_p"]) == p
    assert row["B_p"] != "0.0000"


def test_low_power_factor_is_recorded_without_four_decimal_evidence_rounding(real_sample) -> None:
    p = 5.0
    q = -3450.0
    s = (p * p + q * q) ** 0.5
    pf = p / s
    measurement = replace(real_sample.phase_b.measurement, p=p, q=q, s=s, pf=pf)
    block = replace(real_sample.phase_b, measurement=measurement)
    sample = replace(real_sample, phase_b=block)
    row = sample_to_csv_row(sample, sample.timing.cycle_finished_utc.isoformat(), 0.0)

    assert row["B_p"] == repr(p)
    assert row["B_q"] == repr(q)
    assert row["B_pf"] == repr(pf)
    assert float(row["B_pf"]) == pf



def test_recording_manager_reports_active_recording_owner_and_current_interval(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    manager = RecordingManager(tmp_path, (device_config,), store, bus, "0.2.4")
    manager.start(device_config.id, 10.0, "")
    status = manager.active_recordings()
    assert len(status) == 1
    assert status[0]["device_id"] == device_config.id
    assert status[0]["device_name"] == device_config.name
    assert status[0]["interval_s"] == 10.0
    assert status[0]["session_dir"].endswith(device_config.id)
    assert status[0]["started_utc"].endswith("+00:00")

    manager.set_interval(device_config.id, 20.0)
    assert manager.active_recordings()[0]["interval_s"] == 20.0
    manager.stop(device_config.id)
    assert manager.active_recordings() == ()
    manager.stop_all()


def test_stop_all_attempts_every_recorder_and_always_stops_event_consumer(tmp_path) -> None:
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    class FakeRecorder:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1
            if self.fail:
                raise RuntimeError(f"stop failed for {self.name}")

    bus = RuntimeEventBus()
    manager = RecordingManager(tmp_path, (), RuntimeStore(), bus, "0.3.3")
    first = FakeRecorder("a", fail=True)
    second = FakeRecorder("b")
    manager._active["a"] = first
    manager._active["b"] = second
    manager.start_background()

    with pytest.raises(RuntimeError) as exc_info:
        manager.stop_all()

    assert first.stop_calls == 1
    assert second.stop_calls == 1
    assert manager._active == {}
    assert manager._stop.is_set()
    assert manager._thread.is_alive() is False
    assert manager._subscriber not in bus._subscribers
    assert "stop failed for a" in str(exc_info.value)


def test_background_recording_write_failure_becomes_explicit_error_without_stopping_consumer(
    tmp_path, real_sample, device_config, monkeypatch
) -> None:
    import json
    import threading

    from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity
    from emonio_viewer.runtime.store import RuntimeStore

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    observer = bus.subscribe(maxsize=8)
    manager = RecordingManager(tmp_path, (device_config,), store, bus, "0.4.8")
    manager.start(device_config.id, device_config.poll_interval_s, "")
    recorder = manager._active[device_config.id]
    failure_seen = threading.Event()

    def fail_measurement_write(_row):
        failure_seen.set()
        raise OSError("simulated recording write failure")

    monkeypatch.setattr(recorder._writers, "write_measurement", fail_measurement_write)
    manager.start_background()
    next_sample = with_finish_time(real_sample, recorder._next_record_utc)
    bus.publish(next_sample)

    assert failure_seen.wait(timeout=1.0)
    for _ in range(100):
        if manager.recording_failures():
            break
        threading.Event().wait(0.01)

    assert manager._thread.is_alive() is True
    assert manager.active_recordings() == ()
    failures = manager.recording_failures()
    assert len(failures) == 1
    assert failures[0]["device_id"] == device_config.id
    assert failures[0]["state"] == "ERROR"
    assert failures[0]["error_type"] == "OSError"
    assert failures[0]["error_detail"] == "simulated recording write failure"

    diagnostic = None
    for _ in range(8):
        event = observer.get(timeout=1.0)
        if isinstance(event, DiagnosticEvent) and event.event == "RECORDING_WRITE_ERROR":
            diagnostic = event
            break
    assert diagnostic is not None
    assert diagnostic.device_id == device_config.id
    assert diagnostic.severity is Severity.ERROR
    assert "OSError: simulated recording write failure" in diagnostic.detail

    metadata = json.loads((recorder.session_dir / "session.json").read_text(encoding="utf-8"))
    assert metadata["recording_state"] == "ERROR"
    assert metadata["failure"]["type"] == "OSError"
    assert metadata["failure"]["detail"] == "simulated recording write failure"

    manager.stop_all()
    bus.unsubscribe(observer)
