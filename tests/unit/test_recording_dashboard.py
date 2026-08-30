from datetime import timedelta


def test_live_recording_status_exposes_session_progress(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.recording.recorder import SessionRecorder

    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(
        tmp_path,
        real_sample,
        device_config,
        10.0,
        "0.4.13",
        started,
    )

    status = recorder.recording_status()

    assert status["state"] == "RECORDING"
    assert status["session_id"].endswith(device_config.id)
    assert status["application_version"] == "0.4.13"
    assert status["acquisition_interval_s"] == device_config.poll_interval_s
    assert status["records_written"] == 1
    assert status["record_points_missed"] == 0
    assert status["eligible_samples_seen"] == 1
    assert status["invalid_cycles_seen"] == 0
    assert status["last_recorded_cycle_id"] == real_sample.identity.cycle_id
    assert status["last_recorded_utc"] == started.isoformat()
    assert status["next_record_utc"] == (started + timedelta(seconds=10)).isoformat()

    recorder.stop(started)


def test_live_recording_status_updates_missed_and_invalid_counters(
    tmp_path, real_sample, device_config
) -> None:
    from dataclasses import replace
    from emonio_viewer.recording.recorder import SessionRecorder

    started = real_sample.timing.cycle_finished_utc
    recorder = SessionRecorder.create(
        tmp_path,
        real_sample,
        device_config,
        10.0,
        "0.4.13",
        started,
    )
    later = replace(
        real_sample,
        identity=replace(real_sample.identity, cycle_id=real_sample.identity.cycle_id + 10),
        timing=replace(real_sample.timing, cycle_finished_utc=started + timedelta(seconds=21)),
    )
    recorder.consider_sample(later)
    recorder.record_invalid_cycle(
        started + timedelta(seconds=22),
        later.identity.cycle_id + 1,
        "simulated invalid acquisition cycle",
    )

    status = recorder.recording_status()

    assert status["records_written"] == 2
    assert status["record_points_missed"] == 1
    assert status["eligible_samples_seen"] == 2
    assert status["invalid_cycles_seen"] == 1
    assert status["last_recorded_cycle_id"] == later.identity.cycle_id
    assert status["last_recorded_utc"] == later.timing.cycle_finished_utc.isoformat()
    assert status["next_record_utc"] == (started + timedelta(seconds=30)).isoformat()

    recorder.stop(started + timedelta(seconds=22))
