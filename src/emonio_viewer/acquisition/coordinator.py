from concurrent.futures import Future
import threading

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.device_evidence.modbus import ModbusDeviceEvidenceReader
from emonio_viewer.device_evidence.model import ModbusDeviceEvidenceValues
from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.modbus.transport import ReadOnlyModbusClient
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity
from emonio_viewer.runtime.store import RuntimeStore

from .lifecycle import AcquisitionLifecycleState, AcquisitionStatus, AcquisitionTransitionError
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
        self._devices: dict[str, DeviceConfig] = {}
        self._workers: dict[str, AcquisitionWorker] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._worker_stops: dict[str, threading.Event] = {}
        self._lifecycle: dict[str, AcquisitionStatus] = {}
        self._connection_offsets: dict[str, int] = {}
        self._started = False

        for device in devices:
            if device.enabled:
                self._register_device(device)

    def _create_worker(
        self,
        device: DeviceConfig,
        *,
        starting_cycle_id: int = 0,
    ) -> AcquisitionWorker:
        client = ReadOnlyModbusClient(
            device.host,
            device.port,
            device.unit_id,
            device.timeout_s,
        )
        return AcquisitionWorker(device, client, starting_cycle_id=starting_cycle_id)

    def _register_device(
        self,
        device: DeviceConfig,
        *,
        starting_cycle_id: int = 0,
    ) -> AcquisitionWorker:
        if device.id in self._devices:
            raise ValueError(f"device already registered: {device.id}")
        self._store.register_device(device)
        worker = self._create_worker(device, starting_cycle_id=starting_cycle_id)
        self._devices[device.id] = device
        self._workers[device.id] = worker
        self._connection_offsets[device.id] = 0
        self._lifecycle[device.id] = AcquisitionStatus(
            device.id,
            AcquisitionLifecycleState.DISCONNECTED,
        )
        return worker

    def device_configs(self) -> tuple[DeviceConfig, ...]:
        with self._lock:
            return tuple(self._devices.values())

    def get_device_config(self, device_id: str) -> DeviceConfig:
        with self._lock:
            try:
                return self._devices[device_id]
            except KeyError as exc:
                raise KeyError(device_id) from exc

    def acquisition_status(self, device_id: str) -> AcquisitionStatus:
        with self._lock:
            try:
                return self._lifecycle[device_id]
            except KeyError as exc:
                raise KeyError(device_id) from exc

    def request_modbus_device_evidence(
        self,
        device_id: str,
        reader: ModbusDeviceEvidenceReader,
    ) -> Future[ModbusDeviceEvidenceValues]:
        with self._lock:
            if not self._started:
                raise RuntimeError("acquisition coordinator is not started")
            status = self._lifecycle.get(device_id)
            if status is None:
                raise KeyError(device_id)
            if status.state is not AcquisitionLifecycleState.RUNNING:
                raise RuntimeError("acquisition worker is not running")
            worker = self._workers[device_id]
        return worker.request_device_evidence(reader)

    def _start_worker(
        self,
        device_id: str,
        worker: AcquisitionWorker,
        *,
        connection_offset: int,
    ) -> None:
        with self._lock:
            thread = self._threads.get(device_id)
            if thread is not None and thread.is_alive():
                raise RuntimeError(f"worker already running: {device_id}")
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_worker,
                args=(worker, stop_event, connection_offset),
                name=f"emonio-{device_id}",
                daemon=False,
            )
            self._worker_stops[device_id] = stop_event
            self._threads[device_id] = thread
            thread.start()
            self._lifecycle[device_id] = AcquisitionStatus(
                device_id,
                AcquisitionLifecycleState.RUNNING,
            )

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
            if device.id in self._devices:
                raise ValueError(f"device already registered: {device.id}")
            starting_cycle_id = 0 if initial_sample is None else initial_sample.identity.cycle_id
            worker = self._register_device(device, starting_cycle_id=starting_cycle_id)
            if initial_sample is not None:
                self._store.publish_sample(initial_sample, initial_connections_opened)
                self._bus.publish(initial_sample)
            if self._started:
                self._start_worker(
                    device.id,
                    worker,
                    connection_offset=self._connection_offsets[device.id],
                )

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("acquisition coordinator already started")
            if self._stop.is_set():
                raise RuntimeError("acquisition coordinator is stopping")
            self._started = True
            workers = tuple(self._workers.items())
        for device_id, worker in workers:
            self._start_worker(
                device_id,
                worker,
                connection_offset=self._connection_offsets[device_id],
            )

    def _run_worker(
        self,
        worker: AcquisitionWorker,
        stop_event: threading.Event,
        connection_offset: int,
    ) -> None:
        def connections_opened() -> int:
            return connection_offset + worker.client.connections_opened

        def publish_sample(sample) -> None:
            self._store.publish_sample(sample, connections_opened())
            self._bus.publish(sample)

        def publish_failure(failure: AcquisitionFailure) -> None:
            self._store.publish_failure(failure, connections_opened())
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

        worker.run(stop_event, publish_sample, publish_failure)

    def disconnect_device(
        self,
        device_id: str,
        join_timeout_s: float = 5.0,
    ) -> AcquisitionStatus:
        with self._lock:
            try:
                status = self._lifecycle[device_id]
            except KeyError as exc:
                raise KeyError(device_id) from exc
            if status.state is not AcquisitionLifecycleState.RUNNING:
                raise AcquisitionTransitionError(
                    AcquisitionStatus(
                        device_id,
                        status.state,
                        "acquisition is not RUNNING",
                    )
                )
            thread = self._threads.get(device_id)
            stop_event = self._worker_stops.get(device_id)
            worker = self._workers[device_id]
            if thread is None or stop_event is None:
                error = AcquisitionStatus(
                    device_id,
                    AcquisitionLifecycleState.ERROR,
                    "running acquisition has no worker thread ownership",
                )
                self._lifecycle[device_id] = error
                raise AcquisitionTransitionError(error)
            self._lifecycle[device_id] = AcquisitionStatus(
                device_id,
                AcquisitionLifecycleState.DISCONNECTING,
            )

        stop_event.set()
        worker.client.close()
        thread.join(timeout=join_timeout_s)

        with self._lock:
            if thread.is_alive():
                error = AcquisitionStatus(
                    device_id,
                    AcquisitionLifecycleState.ERROR,
                    f"acquisition worker did not stop within {join_timeout_s:g} s",
                )
                self._lifecycle[device_id] = error
                raise AcquisitionTransitionError(error)

            self._connection_offsets[device_id] += worker.client.connections_opened
            status = AcquisitionStatus(
                device_id,
                AcquisitionLifecycleState.DISCONNECTED,
            )
            self._lifecycle[device_id] = status
            return status

    def close_clients(self) -> None:
        with self._lock:
            workers = tuple(self._workers.values())
        for worker in workers:
            worker.client.close()

    def stop(self, join_timeout_s: float = 5.0) -> None:
        self._stop.set()
        with self._lock:
            stops = tuple(self._worker_stops.values())
            workers = tuple(self._workers.values())
            threads = tuple(self._threads.items())
        for stop_event in stops:
            stop_event.set()
        for worker in workers:
            worker.client.close()
        for _, thread in threads:
            thread.join(timeout=join_timeout_s)
        alive = [name for name, thread in threads if thread.is_alive()]
        if alive:
            raise RuntimeError(f"workers did not stop: {alive}")
        with self._lock:
            self._started = False
            for device_id in self._lifecycle:
                if self._lifecycle[device_id].state is not AcquisitionLifecycleState.ERROR:
                    self._lifecycle[device_id] = AcquisitionStatus(
                        device_id,
                        AcquisitionLifecycleState.DISCONNECTED,
                    )
