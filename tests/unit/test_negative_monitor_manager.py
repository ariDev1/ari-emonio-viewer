from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.recording.negative_monitor import (
    MonitorBoundary, MonitorPhase, NegativeCondition, NegativeMonitorConfig,
)
from emonio_viewer.recording.recorder import (
    RecordingManager, RecordingOwner, SessionRecorder,
)
from emonio_viewer.runtime.events import RuntimeEventBus


class FakeStore:
    def __init__(self, samples=None):
        self.samples = samples or {}

    def get_device(self, device_id):
        return SimpleNamespace(last_sample=self.samples.get(device_id))


def device(device_id, poll=2.0):
    return DeviceConfig(device_id, device_id.upper(), "192.0.2.1", poll_interval_s=poll)


def config(device_id="a", interval=2.0, phases=(MonitorPhase.A, MonitorPhase.B, MonitorPhase.C)):
    return NegativeMonitorConfig(
        device_id,
        NegativeCondition.P_NEGATIVE,
        phases,
        interval,
    )


def sample_for(device_id="a", cycle=100):
    return SimpleNamespace(identity=SimpleNamespace(device_id=device_id, cycle_id=cycle))


def manager(tmp_path, devices=None, store=None):
    return RecordingManager(
        tmp_path,
        tuple(devices or (device("a"),)),
        store or FakeStore(),
        RuntimeEventBus(),
        "0.4.17",
    )


def test_monitor_configuration_is_per_device_and_status_is_sorted(tmp_path):
    instance = manager(tmp_path, [device("b"), device("a")])
    assert instance.configure_monitor(config("b"))["state"] == "OFF"
    assert instance.configure_monitor(config("a", phases=(MonitorPhase.C,)))["state"] == "OFF"
    statuses = instance.monitor_statuses()
    assert [item["device_id"] for item in statuses] == ["a", "b"]
    assert statuses[0] == {
        "device_id": "a",
        "state": "OFF",
        "config": {
            "condition": "P_NEGATIVE",
            "phases": ["C"],
            "recording_interval_s": 2.0,
        },
        "active_conditions": [],
        "last_event": None,
    }


def test_new_manager_has_no_enabled_monitor_state(tmp_path):
    instance = manager(tmp_path)
    instance.configure_monitor(config())
    assert instance.monitor_statuses()[0]["state"] == "OFF"
    second = manager(tmp_path / "other")
    assert second.monitor_statuses() == ()


def test_monitor_commands_respect_command_disable(tmp_path):
    instance = manager(tmp_path)
    instance.configure_monitor(config())
    instance.disable_commands()
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        instance.configure_monitor(config())
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        instance.enable_monitor("a")
    with pytest.raises(RuntimeError, match="recording commands disabled"):
        instance.disable_monitor("a")


def test_configure_monitor_rejects_interval_below_acquisition(tmp_path):
    instance = manager(tmp_path, [device("a", poll=2.0)])
    with pytest.raises(ValueError, match="recording interval.*acquisition interval"):
        instance.configure_monitor(config(interval=1.0))


def test_enable_monitor_snapshots_cycle_floor_but_does_not_evaluate_store_sample(tmp_path):
    observed = sample_for(cycle=100)
    instance = manager(tmp_path, store=FakeStore({"a": observed}))
    instance.configure_monitor(config())
    status = instance.enable_monitor("a")
    assert status["state"] == "WAITING"
    runtime = instance._monitor_runtime["a"]
    assert runtime.enable_floor_cycle_id == 100
    assert runtime.previous_cycle_id is None
    assert runtime.active_keys == set()
    assert runtime.pending_boundary is MonitorBoundary.MONITOR_START


def test_enable_monitor_without_store_sample_uses_none_floor(tmp_path):
    instance = manager(tmp_path)
    instance.configure_monitor(config())
    instance.enable_monitor("a")
    assert instance._monitor_runtime["a"].enable_floor_cycle_id is None


def test_enable_requires_configuration(tmp_path):
    instance = manager(tmp_path)
    with pytest.raises(RuntimeError, match="monitor not configured"):
        instance.enable_monitor("a")


def test_manual_start_sets_manual_owner_and_stop_clears_it(tmp_path, monkeypatch):
    observed = sample_for(cycle=1)
    instance = manager(tmp_path, store=FakeStore({"a": observed}))
    recorder = SimpleNamespace(
        session_dir=tmp_path / "manual",
        stop=lambda: None,
        record_event=lambda *args: None,
    )
    monkeypatch.setattr(
        SessionRecorder,
        "create",
        classmethod(lambda cls, *args, **kwargs: recorder),
    )
    instance.start("a", 2.0)
    assert instance._active_owner["a"] is RecordingOwner.MANUAL
    instance.stop("a")
    assert "a" not in instance._active_owner


def test_owner_state_is_per_emonio(tmp_path):
    instance = manager(tmp_path, [device("a"), device("b")])
    instance._active_owner["a"] = RecordingOwner.MANUAL
    instance._active_owner["b"] = RecordingOwner.NEGATIVE_CONDITION_MONITOR
    assert instance._active_owner["a"] is RecordingOwner.MANUAL
    assert instance._active_owner["b"] is RecordingOwner.NEGATIVE_CONDITION_MONITOR


def test_disable_stops_monitor_owned_recording_but_not_manual_owned(tmp_path):
    instance = manager(tmp_path, [device("a"), device("b")])
    instance.configure_monitor(config("a"))
    instance.configure_monitor(config("b"))
    instance.enable_monitor("a")
    instance.enable_monitor("b")
    monitor_recorder = SimpleNamespace(stopped=False)
    monitor_recorder.stop = lambda: setattr(monitor_recorder, "stopped", True)
    manual_recorder = SimpleNamespace(stopped=False)
    manual_recorder.stop = lambda: setattr(manual_recorder, "stopped", True)
    instance._active["a"] = monitor_recorder
    instance._active_owner["a"] = RecordingOwner.NEGATIVE_CONDITION_MONITOR
    instance._active["b"] = manual_recorder
    instance._active_owner["b"] = RecordingOwner.MANUAL
    assert instance.disable_monitor("a")["state"] == "OFF"
    assert monitor_recorder.stopped is True
    assert "a" not in instance._active
    assert instance.disable_monitor("b")["state"] == "OFF"
    assert manual_recorder.stopped is False
    assert instance._active["b"] is manual_recorder


def test_configure_while_enabled_applies_disable_semantics(tmp_path):
    instance = manager(tmp_path)
    instance.configure_monitor(config())
    instance.enable_monitor("a")
    status = instance.configure_monitor(config(phases=(MonitorPhase.B,)))
    assert status["state"] == "OFF"
    assert "a" not in instance._monitor_runtime
    assert status["config"]["phases"] == ["B"]


def test_disconnect_marks_reconnect_boundary_and_records_noncycle_event(tmp_path):
    instance = manager(tmp_path)
    instance.configure_monitor(config())
    instance.enable_monitor("a")
    recorder = SimpleNamespace(events=[])
    recorder.record_event = lambda *args: recorder.events.append(args)
    instance._active["a"] = recorder
    instance._active_owner["a"] = RecordingOwner.MANUAL
    occurred = datetime(2026, 8, 31, 8, 30, tzinfo=timezone.utc)
    instance.note_device_disconnect("a", occurred)
    assert instance._monitor_runtime["a"].pending_boundary is MonitorBoundary.RECONNECT
    assert recorder.events == [
        (
            occurred,
            "DEVICE_DISCONNECTED",
            "INFO",
            0,
            "monitor continuity boundary=RECONNECT",
        )
    ]
