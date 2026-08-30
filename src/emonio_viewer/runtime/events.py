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
        self._dropped_deliveries_total = 0
        self._dropped_deliveries_by_device: dict[str, int] = {}

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

    def dropped_deliveries(self, device_id: str | None = None) -> int:
        with self._lock:
            if device_id is None:
                return self._dropped_deliveries_total
            return self._dropped_deliveries_by_device.get(device_id, 0)

    def _record_dropped_delivery(self, event: RuntimeEvent) -> None:
        if isinstance(event, MeasurementSample):
            device_id = event.identity.device_id
        else:
            device_id = event.device_id
        with self._lock:
            self._dropped_deliveries_total += 1
            self._dropped_deliveries_by_device[device_id] = (
                self._dropped_deliveries_by_device.get(device_id, 0) + 1
            )

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
                        dropped = subscriber.get_nowait()
                    except Empty:
                        continue
                    self._record_dropped_delivery(dropped)
