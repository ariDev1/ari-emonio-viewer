from __future__ import annotations

import asyncio

import pytest

from emonio_viewer.acquisition.lifecycle import AcquisitionLifecycleState, AcquisitionStatus
from emonio_viewer.lifecycle.model import DeviceLifecycleCommandError, LifecycleFailureStage
from emonio_viewer.lifecycle.service import DeviceLifecycleService


class FakeSnapshot:
    def __init__(self, state: str = "ONLINE") -> None:
        self.state = type("State", (), {"value": state})()


class FakeStore:
    def __init__(self) -> None:
        self.snapshot = FakeSnapshot()

    def get_device(self, _device_id):
        return self.snapshot


class FakeCoordinator:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.state = AcquisitionLifecycleState.RUNNING
        self.disconnect_error: Exception | None = None
        self.reconnect_error: Exception | None = None

    def acquisition_status(self, device_id):
        return AcquisitionStatus(device_id, self.state)

    def disconnect_device(self, device_id):
        self.trace.append(f"acquisition:{device_id}")
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.state = AcquisitionLifecycleState.DISCONNECTED
        return self.acquisition_status(device_id)

    def reconnect_device(self, device_id):
        self.trace.append(f"reconnect:{device_id}")
        if self.reconnect_error is not None:
            raise self.reconnect_error
        self.state = AcquisitionLifecycleState.RUNNING
        return self.acquisition_status(device_id)


class FakeRecording:
    def __init__(self, trace: list[str], *, active: bool = True) -> None:
        self.trace = trace
        self.active = active
        self.stop_error: Exception | None = None

    def is_active(self, _device_id):
        return self.active

    def stop(self, device_id):
        self.trace.append(f"recording:{device_id}")
        if self.stop_error is not None:
            raise self.stop_error
        self.active = False


class FakeScope:
    def __init__(self, trace: list[str], state: str = "LIVE") -> None:
        self.trace = trace
        self.state = state
        self.stop_error: Exception | None = None

    def status(self, device_id):
        return type(
            "ScopeStatus",
            (),
            {"device_id": device_id, "state": type("State", (), {"value": self.state})()},
        )()

    async def stop(self, device_id):
        self.trace.append(f"scope:{device_id}")
        if self.stop_error is not None:
            raise self.stop_error
        self.state = "DISCONNECTED"
        return self.status(device_id)


def build_service(*, recording_active: bool = True):
    trace: list[str] = []
    coordinator = FakeCoordinator(trace)
    recording = FakeRecording(trace, active=recording_active)
    scope = FakeScope(trace)
    store = FakeStore()
    service = DeviceLifecycleService(coordinator, recording, scope, store)
    return service, coordinator, recording, scope, trace


def test_disconnect_stops_recording_then_scope_then_acquisition() -> None:
    service, coordinator, recording, scope, trace = build_service()

    result = asyncio.run(service.disconnect("emonio-a"))

    assert trace == ["recording:emonio-a", "scope:emonio-a", "acquisition:emonio-a"]
    assert result.acquisition_state == "DISCONNECTED"
    assert result.recording_state == "STOPPED"
    assert result.scope_state == "DISCONNECTED"
    assert result.failed_stage is None


def test_disconnect_skips_recording_stop_when_not_active_but_still_stops_scope_first() -> None:
    service, coordinator, recording, scope, trace = build_service(recording_active=False)

    result = asyncio.run(service.disconnect("emonio-a"))

    assert trace == ["scope:emonio-a", "acquisition:emonio-a"]
    assert result.acquisition_state == "DISCONNECTED"


def test_recording_failure_stops_later_stages_without_rollback() -> None:
    service, coordinator, recording, scope, trace = build_service()
    recording.stop_error = RuntimeError("recording finalization failed")

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.disconnect("emonio-a"))

    result = exc_info.value.result
    assert trace == ["recording:emonio-a"]
    assert result.failed_stage is LifecycleFailureStage.RECORDING
    assert result.recording_state == "ERROR"
    assert result.acquisition_state == "RUNNING"
    assert scope.state == "LIVE"
    assert "recording finalization failed" in (result.detail or "")


def test_scope_failure_stops_acquisition_stage_without_restarting_recording() -> None:
    service, coordinator, recording, scope, trace = build_service()
    scope.stop_error = RuntimeError("scope cleanup failed")

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.disconnect("emonio-a"))

    result = exc_info.value.result
    assert trace == ["recording:emonio-a", "scope:emonio-a"]
    assert result.failed_stage is LifecycleFailureStage.SCOPE
    assert recording.active is False
    assert result.recording_state == "STOPPED"
    assert result.acquisition_state == "RUNNING"
    assert "scope cleanup failed" in (result.detail or "")


def test_acquisition_failure_reports_exact_final_stage_and_does_not_rollback() -> None:
    service, coordinator, recording, scope, trace = build_service()
    coordinator.disconnect_error = RuntimeError("worker did not stop")

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.disconnect("emonio-a"))

    result = exc_info.value.result
    assert trace == ["recording:emonio-a", "scope:emonio-a", "acquisition:emonio-a"]
    assert result.failed_stage is LifecycleFailureStage.ACQUISITION
    assert result.recording_state == "STOPPED"
    assert result.scope_state == "DISCONNECTED"
    assert "worker did not stop" in (result.detail or "")


def test_reconnect_starts_acquisition_only() -> None:
    service, coordinator, recording, scope, trace = build_service(recording_active=False)
    coordinator.state = AcquisitionLifecycleState.DISCONNECTED
    scope.state = "DISCONNECTED"

    result = asyncio.run(service.reconnect("emonio-a"))

    assert trace == ["reconnect:emonio-a"]
    assert result.acquisition_state == "RUNNING"
    assert result.recording_state == "STOPPED"
    assert result.scope_state == "DISCONNECTED"


def test_commands_for_two_devices_use_independent_locks() -> None:
    service, coordinator, recording, scope, trace = build_service(recording_active=False)

    async def exercise():
        first = service._lock_for("emonio-a")
        second = service._lock_for("emonio-b")
        assert first is not second
        assert service._lock_for("emonio-a") is first

    asyncio.run(exercise())
