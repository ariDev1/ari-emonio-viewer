from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from queue import Empty
import threading

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore

from .csv_writer import CsvWriters, sample_to_csv_row
from .session import create_session_directory, initial_session_metadata


def _validate_recording_interval(interval_s: float, acquisition_interval_s: float) -> None:
    if interval_s <= 0:
        raise ValueError("recording interval must be > 0")
    if interval_s < acquisition_interval_s:
        raise ValueError(
            "recording interval must be greater than or equal to acquisition interval "
            f"({acquisition_interval_s:g} s)"
        )


class SessionRecorder:
    @classmethod
    def create(
        cls,
        root: Path,
        first_sample: MeasurementSample,
        device: DeviceConfig,
        recording_interval_s: float,
        application_version: str,
        started_utc: datetime | None = None,
    ) -> "SessionRecorder":
        _validate_recording_interval(recording_interval_s, device.poll_interval_s)
        start = started_utc or datetime.now(timezone.utc)
        session_id, session_dir = create_session_directory(root, device.id, start)
        metadata = initial_session_metadata(
            session_id=session_id,
            started_utc=start,
            device=device,
            application_version=application_version,
            recording_interval_s=recording_interval_s,
        )
        (session_dir / "session.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recorder = cls(
            session_dir,
            metadata,
            recording_interval_s,
            device.poll_interval_s,
            start,
        )
        recorder.consider_sample(first_sample)
        return recorder

    def __init__(
        self,
        session_dir: Path,
        metadata: dict,
        interval_s: float,
        minimum_interval_s: float,
        started_utc: datetime,
    ) -> None:
        self.session_dir = session_dir
        self._metadata = metadata
        self._minimum_interval_s = minimum_interval_s
        self._interval = timedelta(seconds=interval_s)
        self._next_record_utc = started_utc
        self._writers = CsvWriters(session_dir)
        self._records = 0
        self._missed = 0
        self._valid_samples_seen = 0
        self._invalid_cycles_seen = 0
        self._closed = False

    def consider_sample(self, sample: MeasurementSample) -> None:
        if self._closed:
            raise RuntimeError("recording session is closed")
        if sample.quality not in {SampleQuality.VALID, SampleQuality.DEGRADED}:
            return
        self._valid_samples_seen += 1
        sample_time = sample.timing.cycle_finished_utc

        while sample_time >= self._next_record_utc + self._interval:
            self.record_event(
                self._next_record_utc,
                "RECORD_POINT_MISSED",
                "WARNING",
                sample.identity.cycle_id,
                "no complete valid/degraded sample before next recording boundary",
            )
            self._missed += 1
            self._next_record_utc += self._interval

        if sample_time >= self._next_record_utc:
            self._writers.write_measurement(
                sample_to_csv_row(sample, sample_time.isoformat(), 0.0)
            )
            self._records += 1
            self._next_record_utc += self._interval

    def set_interval(self, interval_s: float, changed_utc: datetime) -> None:
        _validate_recording_interval(interval_s, self._minimum_interval_s)
        self._interval = timedelta(seconds=interval_s)
        self._next_record_utc = changed_utc + self._interval
        self.record_event(
            changed_utc,
            "RECORDING_INTERVAL_CHANGED",
            "INFO",
            0,
            f"interval_s={interval_s}",
        )

    def record_event(
        self,
        when: datetime,
        event: str,
        severity: str,
        cycle_id: int,
        detail: str,
    ) -> None:
        if self._closed:
            raise RuntimeError("recording session is closed")
        self._writers.write_event(
            {
                "utc": when.isoformat(),
                "event": event,
                "severity": severity,
                "cycle_id": str(cycle_id),
                "detail": detail,
            }
        )

    def record_invalid_cycle(self, when: datetime, cycle_id: int, detail: str) -> None:
        self._invalid_cycles_seen += 1
        self.record_event(
            when,
            "ACQUISITION_CYCLE_INVALID",
            "WARNING",
            cycle_id,
            detail,
        )

    def recording_status(self) -> dict:
        device = self._metadata["device"]
        return {
            "device_id": device["id"],
            "device_name": device["name"],
            "interval_s": self._interval.total_seconds(),
            "session_dir": str(self.session_dir),
            "started_utc": self._metadata["started_utc"],
        }

    def stop(self, stopped_utc: datetime | None = None) -> None:
        if self._closed:
            raise RuntimeError("recording session is already closed")
        stop = stopped_utc or datetime.now(timezone.utc)
        if stop >= self._next_record_utc:
            self.record_event(
                self._next_record_utc,
                "RECORD_POINT_MISSED",
                "WARNING",
                0,
                "recording stopped without an eligible sample",
            )
            self._missed += 1

        self._writers.close()
        self._closed = True
        final = dict(self._metadata)
        started = datetime.fromisoformat(self._metadata["started_utc"])
        final.update(
            {
                "stopped_utc": stop.isoformat(),
                "duration_s": (stop - started).total_seconds(),
                "records_written": self._records,
                "record_points_missed": self._missed,
                "valid_samples_seen": self._valid_samples_seen,
                "invalid_cycles_seen": self._invalid_cycles_seen,
            }
        )
        tmp = self.session_dir / "session.json.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(final, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.session_dir / "session.json")


class RecordingManager:
    def __init__(
        self,
        root: Path,
        devices: tuple[DeviceConfig, ...],
        store: RuntimeStore,
        bus: RuntimeEventBus,
        application_version: str,
    ) -> None:
        self._root = root
        self._devices = {device.id: device for device in devices}
        self._store = store
        self._bus = bus
        self._application_version = application_version
        self._active: dict[str, SessionRecorder] = {}
        self._lock = threading.RLock()
        self._accept_commands = True
        self._subscriber = bus.subscribe(maxsize=256)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._consume,
            name="emonio-recorder-events",
            daemon=False,
        )

    def start_background(self) -> None:
        self._thread.start()

    def register_device(self, device: DeviceConfig) -> None:
        """Make a newly qualified runtime device available to the recorder."""
        with self._lock:
            existing = self._devices.get(device.id)
            if existing is not None and existing != device:
                raise ValueError(f"device already registered with different configuration: {device.id}")
            self._devices[device.id] = device

    def disable_commands(self) -> None:
        with self._lock:
            self._accept_commands = False

    def _require_commands_enabled(self) -> None:
        if not self._accept_commands:
            raise RuntimeError("recording commands disabled")

    def start(self, device_id: str, interval_s: float, session_note: str = "") -> Path:
        with self._lock:
            self._require_commands_enabled()
            if device_id in self._active:
                raise RuntimeError("recording already active")
            snapshot = self._store.get_device(device_id)
            if snapshot.last_sample is None:
                raise RuntimeError("no complete sample available for recording start")
            recorder = SessionRecorder.create(
                self._root,
                snapshot.last_sample,
                self._devices[device_id],
                interval_s,
                self._application_version,
            )
            if session_note:
                recorder.record_event(
                    datetime.now(timezone.utc),
                    "SESSION_NOTE",
                    "INFO",
                    snapshot.last_sample.identity.cycle_id,
                    session_note,
                )
            self._active[device_id] = recorder
            return recorder.session_dir

    def stop(self, device_id: str) -> None:
        with self._lock:
            self._require_commands_enabled()
            recorder = self._active.pop(device_id)
            recorder.stop()

    def set_interval(self, device_id: str, interval_s: float) -> None:
        with self._lock:
            self._require_commands_enabled()
            self._active[device_id].set_interval(interval_s, datetime.now(timezone.utc))

    def active_recordings(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(
                self._active[device_id].recording_status()
                for device_id in sorted(self._active)
            )

    def stop_all(self) -> None:
        cleanup_errors: list[str] = []
        with self._lock:
            for device_id in tuple(self._active):
                recorder = self._active.pop(device_id)
                try:
                    recorder.stop()
                except Exception as exc:
                    cleanup_errors.append(f"{device_id}: {str(exc) or type(exc).__name__}")

        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._bus.unsubscribe(self._subscriber)
        if self._thread.is_alive():
            cleanup_errors.append("event thread did not stop")

        if cleanup_errors:
            raise RuntimeError("recording cleanup failed: " + "; ".join(cleanup_errors))

    def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._subscriber.get(timeout=0.1)
            except Empty:
                continue
            with self._lock:
                if isinstance(event, MeasurementSample):
                    recorder = self._active.get(event.identity.device_id)
                    if recorder is not None:
                        recorder.consider_sample(event)
                elif isinstance(event, DiagnosticEvent):
                    recorder = self._active.get(event.device_id)
                    if recorder is not None:
                        recorder.record_invalid_cycle(
                            event.occurred_utc,
                            event.cycle_id,
                            f"{event.event}: {event.detail}",
                        )
