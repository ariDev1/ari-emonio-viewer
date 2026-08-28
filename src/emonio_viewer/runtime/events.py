from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from queue import Empty, Full, Queue
import threading

from emonio_viewer.measurement.model import MeasurementSample


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    device_id: str
    cycle_id: int
    occurred_utc: datetime
    event: str
    severity: Severity
    detail: str


RuntimeEvent = MeasurementSample | DiagnosticEvent


class RuntimeEventBus:
    """Fan out runtime events without blocking acquisition workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Queue[RuntimeEvent]] = []

    def subscribe(self, maxsize: int = 4) -> Queue[RuntimeEvent]:
        if maxsize <= 0:
            raise ValueError("maxsize must be > 0")
        queue: Queue[RuntimeEvent] = Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, subscriber: Queue[RuntimeEvent]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, event: RuntimeEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            while True:
                try:
                    subscriber.put_nowait(event)
                    break
                except Full:
                    try:
                        subscriber.get_nowait()
                    except Empty:
                        continue
