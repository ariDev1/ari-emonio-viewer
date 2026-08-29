from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import socket
import threading
import time

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.device_evidence.modbus import ModbusDeviceEvidenceReader
from emonio_viewer.device_evidence.model import ModbusDeviceEvidenceValues
from emonio_viewer.measurement.model import (
    AcquisitionMetadata,
    BlockState,
    MeasurementIdentity,
    MeasurementSample,
    PhaseMeasurement,
    RawBlockEvidence,
    SampleTiming,
)
from emonio_viewer.measurement.quadrant import classify_flow, classify_quadrant
from emonio_viewer.measurement.validation import Tolerances, validate_complete_measurement
from emonio_viewer.modbus.decoder import MeasurementDecodeError, decode_measurement_block
from emonio_viewer.modbus.protocol import ModbusProtocolError
from emonio_viewer.modbus.register_map import BLOCK_BASES, REGISTER_COUNT
from emonio_viewer.modbus.transport import ReadOnlyModbusClient

from .scheduler import FixedDeadlineScheduler


class AcquisitionFailureKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    PROTOCOL = "PROTOCOL"
    DECODE = "DECODE"
    TRANSPORT = "TRANSPORT"


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    device_id: str
    cycle_id: int
    block: str
    kind: AcquisitionFailureKind
    detail: str
    occurred_utc: datetime


class AcquisitionCycleError(RuntimeError):
    def __init__(self, failure: AcquisitionFailure) -> None:
        super().__init__(f"{failure.block}: {failure.kind.value}: {failure.detail}")
        self.failure = failure


class AcquisitionWorker:
    def __init__(
        self,
        device: DeviceConfig,
        client: ReadOnlyModbusClient,
        *,
        starting_cycle_id: int = 0,
    ) -> None:
        self.device = device
        self.client = client
        self._starting_cycle_id = starting_cycle_id
        self._tolerances = Tolerances()
        self._evidence_lock = threading.Lock()
        self._pending_evidence: tuple[
            ModbusDeviceEvidenceReader, Future[ModbusDeviceEvidenceValues]
        ] | None = None

    @property
    def client_is_connected(self) -> bool:
        return self.client.is_connected

    def request_device_evidence(
        self,
        reader: ModbusDeviceEvidenceReader,
    ) -> Future[ModbusDeviceEvidenceValues]:
        """Queue one read-only evidence operation for the next cycle boundary."""
        with self._evidence_lock:
            if self._pending_evidence is not None:
                return self._pending_evidence[1]
            future: Future[ModbusDeviceEvidenceValues] = Future()
            self._pending_evidence = (reader, future)
            return future

    def _run_pending_device_evidence(self) -> None:
        with self._evidence_lock:
            pending = self._pending_evidence
            self._pending_evidence = None
        if pending is None:
            return

        reader, future = pending
        if future.cancelled():
            return
        try:
            values = reader.read(self.client)
        except Exception as exc:
            future.set_exception(exc)
        else:
            future.set_result(values)

    def _fail_pending_device_evidence(self) -> None:
        with self._evidence_lock:
            pending = self._pending_evidence
            self._pending_evidence = None
        if pending is None:
            return
        _, future = pending
        if not future.done():
            future.set_exception(RuntimeError("acquisition worker stopped"))

    def _failure(
        self,
        *,
        cycle_id: int,
        block: str,
        kind: AcquisitionFailureKind,
        detail: str,
    ) -> AcquisitionCycleError:
        return AcquisitionCycleError(
            AcquisitionFailure(
                device_id=self.device.id,
                cycle_id=cycle_id,
                block=block,
                kind=kind,
                detail=detail,
                occurred_utc=datetime.now(timezone.utc),
            )
        )

    def _read_block(self, name: str, base: int, cycle_id: int) -> BlockState:
        try:
            words = self.client.read_holding_registers(base, REGISTER_COUNT)
            acquired_utc = datetime.now(timezone.utc)
            values = decode_measurement_block(words)
        except socket.timeout as exc:
            self.client.close()
            raise self._failure(
                cycle_id=cycle_id,
                block=name,
                kind=AcquisitionFailureKind.TIMEOUT,
                detail=str(exc),
            ) from exc
        except ModbusProtocolError as exc:
            self.client.close()
            raise self._failure(
                cycle_id=cycle_id,
                block=name,
                kind=AcquisitionFailureKind.PROTOCOL,
                detail=str(exc),
            ) from exc
        except MeasurementDecodeError as exc:
            self.client.close()
            raise self._failure(
                cycle_id=cycle_id,
                block=name,
                kind=AcquisitionFailureKind.DECODE,
                detail=str(exc),
            ) from exc
        except OSError as exc:
            self.client.close()
            raise self._failure(
                cycle_id=cycle_id,
                block=name,
                kind=AcquisitionFailureKind.TRANSPORT,
                detail=str(exc),
            ) from exc

        measurement = PhaseMeasurement(**values)
        return BlockState(
            measurement=measurement,
            quadrant=classify_quadrant(measurement.p, measurement.q),
            flow=classify_flow(measurement.p),
            acquired_utc=acquired_utc,
            raw=RawBlockEvidence(base_register=base, words=tuple(words)),
        )

    def run_cycle(self, cycle_id: int, schedule_lag_ms: float = 0.0) -> MeasurementSample:
        start_utc = datetime.now(timezone.utc)
        start_ns = time.monotonic_ns()

        blocks: dict[str, BlockState] = {}
        for name, base in BLOCK_BASES.items():
            blocks[name] = self._read_block(name, base, cycle_id)

        finish_ns = time.monotonic_ns()
        finish_utc = datetime.now(timezone.utc)
        validation = validate_complete_measurement(
            phase_a=blocks["A"].measurement,
            phase_b=blocks["B"].measurement,
            phase_c=blocks["C"].measurement,
            total=blocks["TOTAL"].measurement,
            tolerances=self._tolerances,
        )

        return MeasurementSample(
            identity=MeasurementIdentity(
                schema_version=1,
                device_id=self.device.id,
                device_name=self.device.name,
                device_ip=self.device.host,
                firmware_version=self.device.firmware_version,
                transport="MODBUS_TCP",
                cycle_id=cycle_id,
            ),
            timing=SampleTiming(
                cycle_started_utc=start_utc,
                cycle_finished_utc=finish_utc,
                cycle_started_monotonic_ns=start_ns,
                cycle_finished_monotonic_ns=finish_ns,
                cycle_span_ms=(finish_ns - start_ns) / 1_000_000.0,
            ),
            acquisition=AcquisitionMetadata(schedule_lag_ms=schedule_lag_ms),
            phase_a=blocks["A"],
            phase_b=blocks["B"],
            phase_c=blocks["C"],
            total=blocks["TOTAL"],
            quality=validation.quality,
            warnings=validation.warnings,
            derived=validation.derived,
        )

    def run(
        self,
        stop_event: threading.Event,
        publish_sample: Callable[[MeasurementSample], None],
        publish_event: Callable[[AcquisitionFailure], None],
    ) -> None:
        cycle_id = self._starting_cycle_id
        scheduler = FixedDeadlineScheduler(
            interval_s=self.device.poll_interval_s,
            first_deadline=time.monotonic(),
        )

        while not stop_event.is_set():
            deadline = scheduler.consume_deadline()
            delay = deadline - time.monotonic()
            if delay > 0 and stop_event.wait(delay):
                break

            started = time.monotonic()
            schedule_lag_ms = max(0.0, (started - deadline) * 1000.0)
            cycle_id += 1
            try:
                publish_sample(self.run_cycle(cycle_id, schedule_lag_ms=schedule_lag_ms))
            except AcquisitionCycleError as exc:
                publish_event(exc.failure)

            self._run_pending_device_evidence()

        self._fail_pending_device_evidence()
        self.client.close()
