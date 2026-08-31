from pathlib import Path
from types import SimpleNamespace

import pytest

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.recording.recorder import RecordingManager, SessionRecorder
from emonio_viewer.recording.trigger import (
    TriggerBlock,
    TriggerConfig,
    TriggerMeasurement,
    TriggerMode,
    TriggerOperator,
)
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore


def make_manager(tmp_path, device, sample=None):
    store = RuntimeStore()
    store.register_device(device)
    if sample is not None:
        store.publish_sample(sample, connections_opened=1)
    bus = RuntimeEventBus()
    return RecordingManager(tmp_path, (device,), store, bus, "0.4.16"), store, bus


def make_config(device, *, threshold=100.0, interval_s=None):
    return TriggerConfig(
        device_id=device.id,
        block=TriggerBlock.A,
        measurement=TriggerMeasurement.P,
        operator=TriggerOperator.GT,
        threshold=threshold,
        mode=TriggerMode.LEVEL,
        recording_interval_s=device.poll_interval_s if interval_s is None else interval_s,
    )


def test_configure_trigger_is_per_device_and_status_is_deterministic(tmp_path):
    a = DeviceConfig("a", "A", "192.0.2.1")
    b = DeviceConfig("b", "B", "192.0.2.2")
    store = RuntimeStore()
    store.register_device(a)
    store.register_device(b)
    manager = RecordingManager(tmp_path, (b, a), store, RuntimeEventBus(), "0.4.16")

    manager.configure_trigger(make_config(b, threshold=2.0))
    manager.configure_trigger(make_config(a, threshold=1.0))

    statuses = manager.trigger_statuses()
    assert [item["device_id"] for item in statuses] == ["a", "b"]
    assert [item["state"] for item in statuses] == ["DISARMED", "DISARMED"]
    assert statuses[0]["config"]["threshold"] == 1.0
    assert statuses[1]["config"]["threshold"] == 2.0


def test_configure_trigger_rejects_interval_below_acquisition(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    with pytest.raises(ValueError, match="recording interval.*acquisition interval"):
        manager.configure_trigger(make_config(device_config, interval_s=device_config.poll_interval_s / 2))


def test_arm_trigger_uses_current_store_cycle_as_post_arm_floor(tmp_path, device_config, real_sample):
    manager, _, _ = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(make_config(device_config))

    status = manager.arm_trigger(device_config.id)

    assert status["state"] == "ARMED"
    assert manager._armed_triggers[device_config.id].arm_floor_cycle_id == real_sample.identity.cycle_id


def test_arm_without_sample_has_no_cycle_floor(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    manager.configure_trigger(make_config(device_config))
    manager.arm_trigger(device_config.id)
    assert manager._armed_triggers[device_config.id].arm_floor_cycle_id is None


def test_arm_while_recording_is_rejected_without_changing_recording(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    manager.configure_trigger(make_config(device_config))
    recorder = SimpleNamespace(recording_status=lambda: {"device_id": device_config.id})
    manager._active[device_config.id] = recorder

    with pytest.raises(RuntimeError, match="recording already active"):
        manager.arm_trigger(device_config.id)

    assert manager._active[device_config.id] is recorder
    assert manager.trigger_statuses()[0]["state"] == "DISARMED"


def test_manual_start_disarms_trigger_before_session_creation(
    tmp_path, device_config, real_sample, monkeypatch
):
    manager, _, _ = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(make_config(device_config))
    manager.arm_trigger(device_config.id)
    fake = SimpleNamespace(session_dir=Path("/tmp/manual"), record_event=lambda *args: None)

    def create(*args, **kwargs):
        assert device_config.id not in manager._armed_triggers
        return fake

    monkeypatch.setattr(SessionRecorder, "create", create)
    path = manager.start(device_config.id, device_config.poll_interval_s, "")

    assert path == Path("/tmp/manual")
    assert manager.trigger_statuses()[0]["state"] == "DISARMED"


def test_manual_start_failure_does_not_restore_armed_trigger(
    tmp_path, device_config, real_sample, monkeypatch
):
    manager, _, _ = make_manager(tmp_path, device_config, real_sample)
    manager.configure_trigger(make_config(device_config))
    manager.arm_trigger(device_config.id)

    def fail(*args, **kwargs):
        assert device_config.id not in manager._armed_triggers
        raise OSError("simulated manual start failure")

    monkeypatch.setattr(SessionRecorder, "create", fail)
    with pytest.raises(OSError, match="simulated manual start failure"):
        manager.start(device_config.id, device_config.poll_interval_s, "")

    assert manager.trigger_statuses()[0]["state"] == "DISARMED"


def test_stop_disarms_armed_trigger_when_no_recording_is_active(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    manager.configure_trigger(make_config(device_config))
    manager.arm_trigger(device_config.id)

    manager.stop(device_config.id)

    assert manager.trigger_statuses()[0]["state"] == "DISARMED"


def test_stop_stops_active_recording_and_leaves_trigger_disarmed(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    manager.configure_trigger(make_config(device_config))
    manager.arm_trigger(device_config.id)
    calls = []
    manager._active[device_config.id] = SimpleNamespace(stop=lambda: calls.append("stop"))

    manager.stop(device_config.id)

    assert calls == ["stop"]
    assert device_config.id not in manager._active
    assert manager.trigger_statuses()[0]["state"] == "DISARMED"


def test_stop_with_neither_recording_nor_armed_trigger_keeps_existing_not_found_semantics(
    tmp_path, device_config
):
    manager, _, _ = make_manager(tmp_path, device_config)
    with pytest.raises(KeyError):
        manager.stop(device_config.id)


def test_trigger_commands_fail_closed_when_commands_disabled(tmp_path, device_config):
    manager, _, _ = make_manager(tmp_path, device_config)
    manager.disable_commands()
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        manager.configure_trigger(make_config(device_config))
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        manager.arm_trigger(device_config.id)
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        manager.disarm_trigger(device_config.id)
