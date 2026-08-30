from collections import deque
from dataclasses import dataclass
import math


LATENCY_WINDOW_SIZE = 4096
LATENCY_STATISTICS_SCOPE = "ROLLING_VALID_CYCLES"


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    cycles_total: int
    valid_cycles: int
    invalid_cycles: int
    timeouts: int
    protocol_errors: int
    decode_errors: int
    reconnects: int
    latency_statistics_scope: str
    latency_window_samples: int
    latency_window_capacity: int
    min_latency_ms: float | None
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    max_latency_ms: float | None
    schedule_lag_ms: float


class DeviceMetrics:
    def __init__(self) -> None:
        self.valid_cycles = 0
        self.invalid_cycles = 0
        self.timeouts = 0
        self.protocol_errors = 0
        self.decode_errors = 0
        self.reconnects = 0
        self._connections_opened = 0
        self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW_SIZE)
        self._schedule_lag_ms = 0.0

    def record_valid_cycle(self, latency_ms: float, schedule_lag_ms: float) -> None:
        self.valid_cycles += 1
        self._latencies.append(latency_ms)
        self._schedule_lag_ms = schedule_lag_ms

    def record_timeout(self) -> None:
        self.invalid_cycles += 1
        self.timeouts += 1

    def record_protocol_error(self) -> None:
        self.invalid_cycles += 1
        self.protocol_errors += 1

    def record_decode_error(self) -> None:
        self.invalid_cycles += 1
        self.decode_errors += 1

    def set_connections_opened(self, total: int) -> None:
        self._connections_opened = max(self._connections_opened, total)
        self.reconnects = max(0, self._connections_opened - 1)

    def record_reconnect(self) -> None:
        self.reconnects += 1

    def snapshot(self) -> MetricsSnapshot:
        values = sorted(self._latencies)
        if values:
            rank = max(0, math.ceil(0.95 * len(values)) - 1)
            minimum = values[0]
            mean = sum(values) / len(values)
            p95 = values[rank]
            maximum = values[-1]
        else:
            minimum = mean = p95 = maximum = None

        return MetricsSnapshot(
            cycles_total=self.valid_cycles + self.invalid_cycles,
            valid_cycles=self.valid_cycles,
            invalid_cycles=self.invalid_cycles,
            timeouts=self.timeouts,
            protocol_errors=self.protocol_errors,
            decode_errors=self.decode_errors,
            reconnects=self.reconnects,
            latency_statistics_scope=LATENCY_STATISTICS_SCOPE,
            latency_window_samples=len(self._latencies),
            latency_window_capacity=LATENCY_WINDOW_SIZE,
            min_latency_ms=minimum,
            mean_latency_ms=mean,
            p95_latency_ms=p95,
            max_latency_ms=maximum,
            schedule_lag_ms=self._schedule_lag_ms,
        )
