from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from emonio_viewer.acquisition.lifecycle import (
    AcquisitionLifecycleState,
    AcquisitionStatus,
    AcquisitionTransitionError,
)
from emonio_viewer.lifecycle.model import DeviceLifecycleCommandError
from emonio_viewer.lifecycle.service import DeviceLifecycleService


class NoRecording:
    def active_recordings(self):
        return ()


class NoScope:
    def status(self, device_id):
        return SimpleNamespace(device_id=device_id, state=SimpleNamespace(value="DISCONNECTED"))

    async def stop(self, device_id):
        return self.status(device_id)


class OnlineStore:
    def get_device(self, _device_id):
        return SimpleNamespace(state=SimpleNamespace(value="ONLINE"))


class TransitionCoordinator:
    def __init__(self, state: AcquisitionLifecycleState, detail: str) -> None:
        self.state = state
        self.detail = detail

    def acquisition_status(self, device_id):
        return AcquisitionStatus(device_id, self.state, self.detail)

    def disconnect_device(self, device_id):
        raise AcquisitionTransitionError(AcquisitionStatus(device_id, self.state, self.detail))

    def reconnect_device(self, device_id):
        raise AcquisitionTransitionError(AcquisitionStatus(device_id, self.state, self.detail))


def _service(state: AcquisitionLifecycleState, detail: str) -> DeviceLifecycleService:
    return DeviceLifecycleService(
        TransitionCoordinator(state, detail),
        NoRecording(),
        NoScope(),
        OnlineStore(),
    )


def test_duplicate_disconnect_is_a_structured_transition_conflict() -> None:
    service = _service(
        AcquisitionLifecycleState.DISCONNECTED,
        "acquisition is not RUNNING",
    )

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.disconnect("emonio-a"))

    assert exc_info.value.conflict is True
    assert exc_info.value.result.acquisition_state == "DISCONNECTED"


def test_duplicate_reconnect_is_a_structured_transition_conflict() -> None:
    service = _service(
        AcquisitionLifecycleState.RUNNING,
        "acquisition is not DISCONNECTED",
    )

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.reconnect("emonio-a"))

    assert exc_info.value.conflict is True
    assert exc_info.value.result.acquisition_state == "RUNNING"


def test_acquisition_cleanup_failure_is_not_misclassified_as_conflict() -> None:
    service = _service(
        AcquisitionLifecycleState.ERROR,
        "acquisition worker did not stop within 5 s",
    )

    with pytest.raises(DeviceLifecycleCommandError) as exc_info:
        asyncio.run(service.disconnect("emonio-a"))

    assert exc_info.value.conflict is False
    assert exc_info.value.result.acquisition_state == "ERROR"
