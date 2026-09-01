from emonio_viewer.load_control.model import ControlMode, SafeState
from emonio_viewer.load_control.state_machine import ControlStateMachine, TripReason


def test_startup_is_disabled_and_safe_is_unconfirmed():
    machine = ControlStateMachine()
    assert machine.mode is ControlMode.DISABLED
    assert machine.safe_state is SafeState.SAFE_UNCONFIRMED
    assert machine.trip_reason is None


def test_operator_disable_from_enabled_is_not_a_trip():
    machine = ControlStateMachine()
    machine.enable()
    machine.disable()
    assert machine.mode is ControlMode.DISABLED
    assert machine.trip_reason is None
    assert machine.safe_state is SafeState.SAFE_UNCONFIRMED


def test_trip_is_latched_and_disable_does_not_clear_it():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.disable()
    assert machine.mode is ControlMode.TRIPPED
    assert machine.trip_reason is TripReason.ACTUATOR_CONNECTION_LOST
    assert machine.safe_state is SafeState.SAFE_UNCONFIRMED


def test_explicit_enable_clears_trip_after_external_gate_has_passed():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.enable()
    assert machine.mode is ControlMode.ENABLED
    assert machine.trip_reason is None
    assert machine.safe_state is SafeState.NOT_REQUIRED


def test_safe_confirmation_is_independent_of_control_mode():
    machine = ControlStateMachine()
    machine.mark_safe_confirmed()
    assert machine.mode is ControlMode.DISABLED
    assert machine.safe_state is SafeState.SAFE_CONFIRMED
