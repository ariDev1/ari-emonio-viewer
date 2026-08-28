from collections.abc import Callable
from dataclasses import dataclass
import threading
import time

from emonio_viewer.acquisition.state import DeviceEvent, DeviceState, DeviceStateMachine
from emonio_viewer.acquisition.worker import AcquisitionFailure, AcquisitionFailureKind
from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.diagnostics.metrics import DeviceMetrics, MetricsSnapshot
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    device_id: str
    state: DeviceState
    last_sample: MeasurementSample | None
    sample_age_s: float | None
    cycles_valid: int
    cycles_invalid: int
    metrics: MetricsSnapshot


@dataclass(slots=True)
class _DeviceRuntime:
    config: DeviceConfig
    machine: DeviceStateMachine
    metrics: DeviceMetrics
    last_sample: MeasurementSample | None = None
    last_sample_monotonic: float | None = None


class RuntimeStore:
    """Own current per-device state without modifying canonical samples."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._devices: dict[str, _DeviceRuntime] = {}

    def register_device(self, config: DeviceConfig) -> None:
        with self._lock:
            if config.id in self._devices:
                raise ValueError(f"device already registered: {config.id}")
            machine = DeviceStateMachine()
            machine.apply(DeviceEvent.START)
            self._devices[config.id] = _DeviceRuntime(config, machine, DeviceMetrics())

    def publish_sample(self, sample: MeasurementSample, connections_opened: int) -> None:
        with self._lock:
            runtime = self._devices[sample.identity.device_id]
            runtime.last_sample = sample
            runtime.last_sample_monotonic = self._clock()
            runtime.metrics.record_valid_cycle(
                sample.timing.cycle_span_ms,
                sample.acquisition.schedule_lag_ms,
            )
            runtime.metrics.set_connections_opened(connections_opened)
            event = (
                DeviceEvent.COMPLETE_DEGRADED_SAMPLE
                if sample.quality is SampleQuality.DEGRADED
                else DeviceEvent.COMPLETE_VALID_SAMPLE
            )
            runtime.machine.apply(event)

    def publish_failure(self, failure: AcquisitionFailure, connections_opened: int) -> None:
        with self._lock:
            runtime = self._devices[failure.device_id]
            if failure.kind is AcquisitionFailureKind.TIMEOUT:
                runtime.metrics.record_timeout()
            elif failure.kind is AcquisitionFailureKind.PROTOCOL:
                runtime.metrics.record_protocol_error()
            elif failure.kind is AcquisitionFailureKind.DECODE:
                runtime.metrics.record_decode_error()
            else:
                runtime.metrics.invalid_cycles += 1
            runtime.metrics.set_connections_opened(connections_opened)
            runtime.machine.apply(DeviceEvent.CYCLE_FAILED)

    def list_devices(self) -> tuple[DeviceSnapshot, ...]:
        with self._lock:
            ids = tuple(self._devices)
        return tuple(self.get_device(device_id) for device_id in ids)

    def get_device(self, device_id: str) -> DeviceSnapshot:
        with self._lock:
            runtime = self._devices[device_id]
            age = (
                None
                if runtime.last_sample_monotonic is None
                else max(0.0, self._clock() - runtime.last_sample_monotonic)
            )
            threshold = 3.0 * runtime.config.poll_interval_s
            if (
                age is not None
                and age > threshold
                and runtime.machine.state in {DeviceState.ONLINE, DeviceState.DEGRADED}
            ):
                runtime.machine.apply(DeviceEvent.STALE_THRESHOLD_EXCEEDED)
            metrics = runtime.metrics.snapshot()
            return DeviceSnapshot(
                device_id=device_id,
                state=runtime.machine.state,
                last_sample=runtime.last_sample,
                sample_age_s=age,
                cycles_valid=metrics.valid_cycles,
                cycles_invalid=metrics.invalid_cycles,
                metrics=metrics,
            )
