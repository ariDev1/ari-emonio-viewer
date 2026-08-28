import pytest

from emonio_viewer.acquisition.state import (
    DeviceEvent,
    DeviceState,
    DeviceStateMachine,
    InvalidStateTransition,
)


def test_online_timeout_becomes_stale_and_recovery_becomes_online() -> None:
    machine = DeviceStateMachine()
    machine.apply(DeviceEvent.START)
    machine.apply(DeviceEvent.CONNECTED)
    machine.apply(DeviceEvent.COMPLETE_VALID_SAMPLE)
    assert machine.state is DeviceState.ONLINE
    machine.apply(DeviceEvent.STALE_THRESHOLD_EXCEEDED)
    assert machine.state is DeviceState.STALE
    machine.apply(DeviceEvent.COMPLETE_VALID_SAMPLE)
    assert machine.state is DeviceState.ONLINE


def test_illegal_transition_is_rejected() -> None:
    machine = DeviceStateMachine()
    with pytest.raises(InvalidStateTransition):
        machine.apply(DeviceEvent.COMPLETE_VALID_SAMPLE)
