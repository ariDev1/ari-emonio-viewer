from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
from queue import Empty
import threading

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity
from emonio_viewer.runtime.store import RuntimeStore

from .csv_writer import CsvWriters, sample_to_csv_row
from .negative_monitor import (
    MonitorBoundary,
    NegativeMonitorConfig,
    NegativeMonitorRuntime,
    invalidate_monitor_continuity,
)
from .session import create_session_directory, initial_session_metadata
from .trigger import (
    TriggerConfig,
    TriggerMode,
    TriggerRuntimeState,
    evaluate_measurement,
    invalidate_crossing_continuity,
)


def _validate_recording_interval(interval_s: float, acquisition_interval_s: float) -> None:
    if not math.isfinite(interval_s):
        raise ValueError("recording interval must be finite")
    if interval_s <= 0:
        raise ValueError("recording interval must be > 0")
    if interval_s < acquisition_interval_s:
        raise ValueError(
            "recording interval must be greater than or equal to acquisition interval "
            f"({acquisition_interval_s:g} s)"
        )


class MonitorOperationalState(str, Enum):
    OFF = "OFF"
    WAITING = "WAITING"
    RECORDING = "RECORDING"
    WAITING_FOR_CLEAR = "WAITING_FOR_CLEAR"


class RecordingOwner(str, Enum):
    MANUAL = "MANUAL"
    NEGATIVE_CONDITION_MONITOR = "NEGATIVE_CONDITION_MONITOR"


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
        trigger_evidence: dict | None = None,
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
            trigger_evidence=trigger_evidence,
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
        self._last_recorded_utc: datetime | None = None
        self._last_recorded_cycle_id: int | None = None
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
            self._last_recorded_utc = sample_time
            self._last_recorded_cycle_id = sample.identity.cycle_id
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
            "state": "RECORDING",
            "interval_s": self._interval.total_seconds(),
            "acquisition_interval_s": self._minimum_interval_s,
            "session_id": self._metadata["session_id"],
            "session_dir": str(self.session_dir),
            "started_utc": self._metadata["started_utc"],
            "application_version": self._metadata["application_version"],
            "records_written": self._records,
            "record_points_missed": self._missed,
            "eligible_samples_seen": self._valid_samples_seen,
            "invalid_cycles_seen": self._invalid_cycles_seen,
            "last_recorded_cycle_id": self._last_recorded_cycle_id,
            "last_recorded_utc": (
                None if self._last_recorded_utc is None else self._last_recorded_utc.isoformat()
            ),
            "next_record_utc": self._next_record_utc.isoformat(),
        }

    def _final_metadata(self, ended_utc: datetime) -> dict:
        final = dict(self._metadata)
        started = datetime.fromisoformat(self._metadata["started_utc"])
        final.update(
            {
                "duration_s": (ended_utc - started).total_seconds(),
                "records_written": self._records,
                "record_points_missed": self._missed,
                "valid_samples_seen": self._valid_samples_seen,
                "invalid_cycles_seen": self._invalid_cycles_seen,
            }
        )
        return final

    def _replace_session_metadata(self, final: dict) -> None:
        tmp = self.session_dir / "session.json.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(final, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.session_dir / "session.json")

    def fail(
        self,
        error: Exception,
        *,
        failed_utc: datetime,
        cycle_id: int,
    ) -> dict:
        if self._closed:
            raise RuntimeError("recording session is already closed")

        error_type = type(error).__name__
        error_detail = str(error) or error_type
        cleanup_error = None
        try:
            self._writers.close()
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {str(exc) or type(exc).__name__}"
        self._closed = True

        failure = {
            "type": error_type,
            "detail": error_detail,
            "cycle_id": cycle_id,
        }
        if cleanup_error is not None:
            failure["cleanup_error"] = cleanup_error

        final = self._final_metadata(failed_utc)
        final.update(
            {
                "recording_state": "ERROR",
                "failed_utc": failed_utc.isoformat(),
                "failure": failure,
            }
        )

        metadata_error = None
        try:
            self._replace_session_metadata(final)
        except Exception as exc:
            metadata_error = f"{type(exc).__name__}: {str(exc) or type(exc).__name__}"

        status = self.recording_status()
        status.update(
            {
                "state": "ERROR",
                "failed_utc": failed_utc.isoformat(),
                "failed_cycle_id": cycle_id,
                "error_type": error_type,
                "error_detail": error_detail,
            }
        )
        if cleanup_error is not None:
            status["cleanup_error"] = cleanup_error
        if metadata_error is not None:
            status["metadata_error"] = metadata_error
        return status

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
        final = self._final_metadata(stop)
        final["stopped_utc"] = stop.isoformat()
        self._replace_session_metadata(final)


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
        self._failed: dict[str, dict] = {}
        self._trigger_configs: dict[str, TriggerConfig] = {}
        self._armed_triggers: dict[str, TriggerRuntimeState] = {}
        self._trigger_last_fired: dict[str, dict] = {}
        self._monitor_configs: dict[str, NegativeMonitorConfig] = {}
        self._monitor_runtime: dict[str, NegativeMonitorRuntime] = {}
        self._monitor_state: dict[str, MonitorOperationalState] = {}
        self._monitor_last_event: dict[str, dict] = {}
        self._active_owner: dict[str, RecordingOwner] = {}
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

    def _monitor_status(self, device_id: str) -> dict:
        config = self._monitor_configs[device_id]
        runtime = self._monitor_runtime.get(device_id)
        active_conditions = []
        if runtime is not None:
            active_conditions = [
                {"phase": key.phase.value, "measurement": key.measurement.value}
                for key in sorted(
                    runtime.active_keys,
                    key=lambda item: (item.phase.value, item.measurement.value),
                )
            ]
        last_event = self._monitor_last_event.get(device_id)
        return {
            "device_id": device_id,
            "state": self._monitor_state.get(
                device_id, MonitorOperationalState.OFF
            ).value,
            "config": {
                "condition": config.condition.value,
                "phases": [phase.value for phase in config.phases],
                "recording_interval_s": config.recording_interval_s,
            },
            "active_conditions": active_conditions,
            "last_event": None if last_event is None else dict(last_event),
        }

    def _disable_monitor_locked(self, device_id: str) -> None:
        if self._active_owner.get(device_id) is RecordingOwner.NEGATIVE_CONDITION_MONITOR:
            recorder = self._active.get(device_id)
            if recorder is not None:
                recorder.stop()
            self._active.pop(device_id, None)
            self._active_owner.pop(device_id, None)
        self._monitor_runtime.pop(device_id, None)
        self._monitor_state[device_id] = MonitorOperationalState.OFF

    def configure_monitor(self, config: NegativeMonitorConfig) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if config.device_id not in self._devices:
                raise KeyError(config.device_id)
            _validate_recording_interval(
                config.recording_interval_s,
                self._devices[config.device_id].poll_interval_s,
            )
            self._disable_monitor_locked(config.device_id)
            self._monitor_configs[config.device_id] = config
            self._monitor_state[config.device_id] = MonitorOperationalState.OFF
            return self._monitor_status(config.device_id)

    def enable_monitor(self, device_id: str) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if device_id not in self._devices:
                raise KeyError(device_id)
            config = self._monitor_configs.get(device_id)
            if config is None:
                raise RuntimeError("monitor not configured")
            snapshot = self._store.get_device(device_id)
            floor = (
                None
                if snapshot.last_sample is None
                else snapshot.last_sample.identity.cycle_id
            )
            self._monitor_runtime[device_id] = NegativeMonitorRuntime(
                config=config,
                enabled_utc=datetime.now(timezone.utc),
                enable_floor_cycle_id=floor,
            )
            self._monitor_state[device_id] = MonitorOperationalState.WAITING
            return self._monitor_status(device_id)

    def disable_monitor(self, device_id: str) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if device_id not in self._devices:
                raise KeyError(device_id)
            if device_id not in self._monitor_configs:
                raise RuntimeError("monitor not configured")
            self._disable_monitor_locked(device_id)
            return self._monitor_status(device_id)

    def monitor_statuses(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(
                self._monitor_status(device_id)
                for device_id in sorted(self._monitor_configs)
            )

    def note_device_disconnect(self, device_id: str, occurred_utc: datetime) -> None:
        with self._lock:
            if device_id not in self._devices:
                raise KeyError(device_id)
            runtime = self._monitor_runtime.get(device_id)
            if runtime is None:
                return
            invalidate_monitor_continuity(runtime, MonitorBoundary.RECONNECT)
            recorder = self._active.get(device_id)
            if recorder is not None:
                recorder.record_event(
                    occurred_utc,
                    "DEVICE_DISCONNECTED",
                    "INFO",
                    0,
                    "monitor continuity boundary=RECONNECT",
                )

    def _trigger_status(self, device_id: str) -> dict:
        config = self._trigger_configs[device_id]
        armed = self._armed_triggers.get(device_id)
        fired = self._trigger_last_fired.get(device_id, {})
        return {
            "device_id": device_id,
            "state": "ARMED" if armed is not None else "DISARMED",
            "config": {
                "block": config.block.value,
                "measurement": config.measurement.value,
                "operator": config.operator.value,
                "threshold": config.threshold,
                "mode": config.mode.value,
                "recording_interval_s": config.recording_interval_s,
            },
            "armed_utc": None if armed is None else armed.armed_utc.isoformat(),
            "last_fired_cycle_id": fired.get("cycle_id"),
            "last_fired_utc": fired.get("utc"),
            "last_fired_value": fired.get("value"),
        }

    def configure_trigger(self, config: TriggerConfig) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if config.device_id not in self._devices:
                raise KeyError(config.device_id)
            _validate_recording_interval(
                config.recording_interval_s,
                self._devices[config.device_id].poll_interval_s,
            )
            self._armed_triggers.pop(config.device_id, None)
            self._trigger_configs[config.device_id] = config
            return self._trigger_status(config.device_id)

    def arm_trigger(self, device_id: str) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if device_id not in self._devices:
                raise KeyError(device_id)
            if device_id in self._active:
                raise RuntimeError("recording already active")
            config = self._trigger_configs.get(device_id)
            if config is None:
                raise RuntimeError("trigger not configured")
            snapshot = self._store.get_device(device_id)
            floor = (
                None
                if snapshot.last_sample is None
                else snapshot.last_sample.identity.cycle_id
            )
            self._armed_triggers[device_id] = TriggerRuntimeState(
                config=config,
                armed_utc=datetime.now(timezone.utc),
                arm_floor_cycle_id=floor,
            )
            return self._trigger_status(device_id)

    def disarm_trigger(self, device_id: str) -> dict:
        with self._lock:
            self._require_commands_enabled()
            if device_id not in self._devices:
                raise KeyError(device_id)
            self._armed_triggers.pop(device_id, None)
            if device_id not in self._trigger_configs:
                raise RuntimeError("trigger not configured")
            return self._trigger_status(device_id)

    def trigger_statuses(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(
                self._trigger_status(device_id)
                for device_id in sorted(self._trigger_configs)
            )

    def start(self, device_id: str, interval_s: float, session_note: str = "") -> Path:
        with self._lock:
            self._require_commands_enabled()
            if device_id in self._active:
                raise RuntimeError("recording already active")
            snapshot = self._store.get_device(device_id)
            if snapshot.last_sample is None:
                raise RuntimeError("no complete sample available for recording start")
            device = self._devices[device_id]
            _validate_recording_interval(interval_s, device.poll_interval_s)
            self._armed_triggers.pop(device_id, None)
            recorder = SessionRecorder.create(
                self._root,
                snapshot.last_sample,
                device,
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
            self._failed.pop(device_id, None)
            self._active[device_id] = recorder
            self._active_owner[device_id] = RecordingOwner.MANUAL
            return recorder.session_dir

    def stop(self, device_id: str) -> None:
        with self._lock:
            self._require_commands_enabled()
            was_armed = self._armed_triggers.pop(device_id, None) is not None
            recorder = self._active.pop(device_id, None)
            if recorder is not None:
                self._active_owner.pop(device_id, None)
                recorder.stop()
                return
            if was_armed:
                return
            raise KeyError(device_id)

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

    def recording_failures(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(dict(self._failed[device_id]) for device_id in sorted(self._failed))

    def stop_all(self) -> None:
        cleanup_errors: list[str] = []
        with self._lock:
            self._armed_triggers.clear()
            self._monitor_runtime.clear()
            for device_id in tuple(self._active):
                recorder = self._active.pop(device_id)
                self._active_owner.pop(device_id, None)
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

    def _recording_failure_event(
        self,
        device_id: str,
        recorder: SessionRecorder,
        cycle_id: int,
        error: Exception,
    ) -> DiagnosticEvent:
        failed_utc = datetime.now(timezone.utc)
        current = self._active.get(device_id)
        if current is recorder:
            self._active.pop(device_id, None)
            self._active_owner.pop(device_id, None)
        status = recorder.fail(error, failed_utc=failed_utc, cycle_id=cycle_id)
        self._failed[device_id] = status

        detail = f"{type(error).__name__}: {str(error) or type(error).__name__}"
        if "metadata_error" in status:
            detail += f"; session metadata update failed: {status['metadata_error']}"
        if "cleanup_error" in status:
            detail += f"; recorder cleanup failed: {status['cleanup_error']}"
        return DiagnosticEvent(
            device_id=device_id,
            cycle_id=cycle_id,
            occurred_utc=failed_utc,
            event="RECORDING_WRITE_ERROR",
            severity=Severity.ERROR,
            detail=detail,
        )

    def _start_triggered_from_sample(
        self,
        device_id: str,
        sample: MeasurementSample,
        fire,
        config: TriggerConfig,
    ) -> SessionRecorder:
        trigger_evidence = {
            "mode": config.mode.value,
            "block": config.block.value,
            "measurement": config.measurement.value,
            "operator": config.operator.value,
            "threshold": config.threshold,
            "fired_cycle_id": fire.cycle_id,
            "fired_utc": fire.fired_utc.isoformat(),
            "fired_value": fire.value,
        }
        recorder = SessionRecorder.create(
            self._root,
            sample,
            self._devices[device_id],
            config.recording_interval_s,
            self._application_version,
            started_utc=fire.fired_utc,
            trigger_evidence=trigger_evidence,
        )
        self._failed.pop(device_id, None)
        self._active[device_id] = recorder
        recorder.record_event(
            fire.fired_utc,
            "TRIGGER_FIRED",
            "INFO",
            fire.cycle_id,
            (
                f"mode={config.mode.value}; block={config.block.value}; "
                f"measurement={config.measurement.value}; operator={config.operator.value}; "
                f"threshold={repr(config.threshold)}; value={repr(fire.value)}"
            ),
        )
        return recorder

    def _triggered_start_failure_event(
        self,
        device_id: str,
        sample: MeasurementSample,
        error: Exception,
    ) -> DiagnosticEvent:
        failed_utc = datetime.now(timezone.utc)
        status = {
            "device_id": device_id,
            "device_name": self._devices[device_id].name,
            "state": "ERROR",
            "start_source": "TRIGGER",
            "session_id": "",
            "session_dir": "",
            "failed_utc": failed_utc.isoformat(),
            "failed_cycle_id": sample.identity.cycle_id,
            "error_type": type(error).__name__,
            "error_detail": str(error) or type(error).__name__,
        }
        self._failed[device_id] = status
        return DiagnosticEvent(
            device_id=device_id,
            cycle_id=sample.identity.cycle_id,
            occurred_utc=failed_utc,
            event="TRIGGERED_RECORDING_START_ERROR",
            severity=Severity.ERROR,
            detail=f"{type(error).__name__}: {str(error) or type(error).__name__}",
        )

    def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._subscriber.get(timeout=0.1)
            except Empty:
                continue

            failure_event = None
            with self._lock:
                if isinstance(event, MeasurementSample):
                    device_id = event.identity.device_id
                    cycle_id = event.identity.cycle_id
                    recorder = self._active.get(device_id)
                    if recorder is not None:
                        try:
                            recorder.consider_sample(event)
                        except Exception as exc:
                            failure_event = self._recording_failure_event(
                                device_id, recorder, cycle_id, exc
                            )
                    else:
                        state = self._armed_triggers.get(device_id)
                        if state is not None:
                            fire = evaluate_measurement(state, event)
                            if fire is not None:
                                config = state.config
                                self._trigger_last_fired[device_id] = {
                                    "cycle_id": fire.cycle_id,
                                    "utc": fire.fired_utc.isoformat(),
                                    "value": fire.value,
                                }
                                self._armed_triggers.pop(device_id, None)
                                try:
                                    self._start_triggered_from_sample(
                                        device_id,
                                        event,
                                        fire,
                                        config,
                                    )
                                except Exception as exc:
                                    started_recorder = self._active.get(device_id)
                                    if started_recorder is not None:
                                        failure_event = self._recording_failure_event(
                                            device_id,
                                            started_recorder,
                                            cycle_id,
                                            exc,
                                        )
                                    else:
                                        failure_event = self._triggered_start_failure_event(
                                            device_id,
                                            event,
                                            exc,
                                        )
                elif isinstance(event, DiagnosticEvent):
                    device_id = event.device_id
                    recorder = self._active.get(device_id)
                    if recorder is not None:
                        try:
                            recorder.record_invalid_cycle(
                                event.occurred_utc,
                                event.cycle_id,
                                f"{event.event}: {event.detail}",
                            )
                        except Exception as exc:
                            failure_event = self._recording_failure_event(
                                device_id, recorder, event.cycle_id, exc
                            )
                    state = self._armed_triggers.get(device_id)
                    if state is not None and state.config.mode is TriggerMode.CROSSING:
                        invalidate_crossing_continuity(state)

            if failure_event is not None:
                self._bus.publish(failure_event)
