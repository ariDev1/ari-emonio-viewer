import threading

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.modbus.transport import ReadOnlyModbusClient
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity
from emonio_viewer.runtime.store import RuntimeStore

from .worker import AcquisitionFailure, AcquisitionWorker


class AcquisitionCoordinator:
    """Own one independent acquisition worker and TCP client per enabled device."""

    def __init__(
        self,
        devices: tuple[DeviceConfig, ...],
        store: RuntimeStore,
        bus: RuntimeEventBus,
    ) -> None:
        self._store = store
        self._bus = bus
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._workers: dict[str, AcquisitionWorker] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._started = False

        for device in devices:
            if device.enabled:
                self._register_worker(device)

    def _register_worker(self, device: DeviceConfig, *, starting_cycle_id: int = 0) -> AcquisitionWorker:
        self._store.register_device(device)
        client = ReadOnlyModbusClient(
            device.host,
            device.port,
            device.unit_id,
            device.timeout_s,
        )
        worker = AcquisitionWorker(device, client, starting_cycle_id=starting_cycle_id)
        self._workers[device.id] = worker
        return worker

    def device_configs(self) -> tuple[DeviceConfig, ...]:
        with self._lock:
            return tuple(worker.device for worker in self._workers.values())

    def get_device_config(self, device_id: str) -> DeviceConfig:
        with self._lock:
            try:
                return self._workers[device_id].device
            except KeyError as exc:
                raise KeyError(device_id) from exc

    def _start_worker(self, device_id: str, worker: AcquisitionWorker) -> None:
        thread = self._threads.get(device_id)
        if thread is not None and thread.is_alive():
            raise RuntimeError(f"worker already running: {device_id}")
        thread = threading.Thread(
            target=self._run_worker,
            args=(worker,),
            name=f"emonio-{device_id}",
            daemon=False,
        )
        self._threads[device_id] = thread
        thread.start()

    def add_device(
        self,
        device: DeviceConfig,
        *,
        initial_sample: MeasurementSample | None = None,
        initial_connections_opened: int = 0,
    ) -> None:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("acquisition coordinator is stopping")
            if device.id in self._workers:
                raise ValueError(f"device already registered: {device.id}")
            starting_cycle_id = 0 if initial_sample is None else initial_sample.identity.cycle_id
            worker = self._register_worker(device, starting_cycle_id=starting_cycle_id)
            if initial_sample is not None:
                self._store.publish_sample(initial_sample, initial_connections_opened)
                self._bus.publish(initial_sample)
            if self._started:
                self._start_worker(device.id, worker)

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("acquisition coordinator already started")
            self._started = True
            for device_id, worker in self._workers.items():
                self._start_worker(device_id, worker)

    def _run_worker(self, worker: AcquisitionWorker) -> None:
        def publish_sample(sample) -> None:
            self._store.publish_sample(sample, worker.client.connections_opened)
            self._bus.publish(sample)

        def publish_failure(failure: AcquisitionFailure) -> None:
            self._store.publish_failure(failure, worker.client.connections_opened)
            self._bus.publish(
                DiagnosticEvent(
                    device_id=failure.device_id,
                    cycle_id=failure.cycle_id,
                    occurred_utc=failure.occurred_utc,
                    event=f"ACQUISITION_{failure.kind.value}",
                    severity=Severity.WARNING,
                    detail=f"{failure.block}: {failure.detail}",
                )
            )

        worker.run(self._stop, publish_sample, publish_failure)

    def close_clients(self) -> None:
        with self._lock:
            workers = tuple(self._workers.values())
        for worker in workers:
            worker.client.close()

    def stop(self, join_timeout_s: float = 5.0) -> None:
        self._stop.set()
        self.close_clients()
        with self._lock:
            threads = tuple(self._threads.items())
        for _, thread in threads:
            thread.join(timeout=join_timeout_s)
        alive = [name for name, thread in threads if thread.is_alive()]
        if alive:
            raise RuntimeError(f"workers did not stop: {alive}")
        with self._lock:
            self._started = False
