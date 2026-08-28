from enum import Enum


class DeviceState(str, Enum):
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
    STOPPED = "STOPPED"


class DeviceEvent(str, Enum):
    START = "START"
    CONNECTED = "CONNECTED"
    COMPLETE_VALID_SAMPLE = "COMPLETE_VALID_SAMPLE"
    COMPLETE_DEGRADED_SAMPLE = "COMPLETE_DEGRADED_SAMPLE"
    CYCLE_FAILED = "CYCLE_FAILED"
    STALE_THRESHOLD_EXCEEDED = "STALE_THRESHOLD_EXCEEDED"
    STOP = "STOP"


class InvalidStateTransition(RuntimeError):
    """Raised when a device event is not valid for the current state."""


class DeviceStateMachine:
    def __init__(self) -> None:
        self.state = DeviceState.STARTING

    def apply(self, event: DeviceEvent) -> DeviceState:
        if event is DeviceEvent.STOP:
            self.state = DeviceState.STOPPED
            return self.state

        transitions = {
            (DeviceState.STARTING, DeviceEvent.START): DeviceState.CONNECTING,
            (DeviceState.CONNECTING, DeviceEvent.CONNECTED): DeviceState.CONNECTING,
            (DeviceState.CONNECTING, DeviceEvent.COMPLETE_VALID_SAMPLE): DeviceState.ONLINE,
            (DeviceState.CONNECTING, DeviceEvent.COMPLETE_DEGRADED_SAMPLE): DeviceState.DEGRADED,
            (DeviceState.ONLINE, DeviceEvent.COMPLETE_VALID_SAMPLE): DeviceState.ONLINE,
            (DeviceState.ONLINE, DeviceEvent.COMPLETE_DEGRADED_SAMPLE): DeviceState.DEGRADED,
            (DeviceState.DEGRADED, DeviceEvent.COMPLETE_VALID_SAMPLE): DeviceState.ONLINE,
            (DeviceState.DEGRADED, DeviceEvent.COMPLETE_DEGRADED_SAMPLE): DeviceState.DEGRADED,
            (DeviceState.ONLINE, DeviceEvent.STALE_THRESHOLD_EXCEEDED): DeviceState.STALE,
            (DeviceState.DEGRADED, DeviceEvent.STALE_THRESHOLD_EXCEEDED): DeviceState.STALE,
            (DeviceState.STALE, DeviceEvent.COMPLETE_VALID_SAMPLE): DeviceState.ONLINE,
            (DeviceState.STALE, DeviceEvent.COMPLETE_DEGRADED_SAMPLE): DeviceState.DEGRADED,
            (DeviceState.CONNECTING, DeviceEvent.CYCLE_FAILED): DeviceState.OFFLINE,
            (DeviceState.ONLINE, DeviceEvent.CYCLE_FAILED): DeviceState.ONLINE,
            (DeviceState.DEGRADED, DeviceEvent.CYCLE_FAILED): DeviceState.DEGRADED,
            (DeviceState.STALE, DeviceEvent.CYCLE_FAILED): DeviceState.OFFLINE,
            (DeviceState.OFFLINE, DeviceEvent.COMPLETE_VALID_SAMPLE): DeviceState.ONLINE,
            (DeviceState.OFFLINE, DeviceEvent.COMPLETE_DEGRADED_SAMPLE): DeviceState.DEGRADED,
            (DeviceState.OFFLINE, DeviceEvent.CYCLE_FAILED): DeviceState.OFFLINE,
        }
        key = (self.state, event)
        if key not in transitions:
            raise InvalidStateTransition(f"{self.state.value} + {event.value}")
        self.state = transitions[key]
        return self.state
