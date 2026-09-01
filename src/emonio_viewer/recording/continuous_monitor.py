from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty

from emonio_viewer.measurement.model import MeasurementSample
from emonio_viewer.runtime.events import DiagnosticEvent, Severity

from .negative_monitor import (
    ConditionKey,
    MonitorBoundary,
    NegativeCondition,
    NegativeMonitorEvaluation,
    NegativeMonitorEvent,
    evaluate_monitor_sample,
    extract_condition_value,
    invalidate_monitor_continuity,
)
from .recorder import (
    MonitorOperationalState,
    RecordingManager as BaseRecordingManager,
    RecordingOwner,
    SessionRecorder as BaseSessionRecorder,
    _validate_recording_interval,
)
from .session import create_session_directory, initial_session_metadata


class SessionRecorder(BaseSessionRecorder):
    """Session recorder used only for monitor-owned automatic sessions."""

    @classmethod
    def create(
        cls,
        root: Path,
        first_sample: MeasurementSample,
        device,
        recording_interval_s: float,
        application_version: str,
        started_utc: datetime | None = None,
        monitor_evidence: dict | None = None,
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
        if monitor_evidence is not None:
            start_source = (
                "Q_THRESHOLD_MONITOR"
                if monitor_evidence.get("condition") == NegativeCondition.Q_THRESHOLD.value
                else "NEGATIVE_CONDITION_MONITOR"
            )
            metadata["recording"] = {
                "interval_s": recording_interval_s,
                "start_source": start_source,
                "monitor": dict(monitor_evidence),
            }
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


class NegativeMonitorRecordingManager(BaseRecordingManager):
    """Recording manager with continuous condition-monitor automation.

    The canonical acquisition and RuntimeEventBus paths are unchanged. This class
    replaces only the automation consumer behavior of the published base manager.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._monitor_active_values: dict[str, dict[ConditionKey, float]] = {}

    @staticmethod
    def _monitor_source(config) -> str:
        if config.condition is NegativeCondition.Q_THRESHOLD:
            return "Q_THRESHOLD_MONITOR"
        return "NEGATIVE_CONDITION_MONITOR"

    def _monitor_status(self, device_id: str) -> dict:
        status = super()._monitor_status(device_id)
        config = self._monitor_configs.get(device_id)
        if config is not None and config.condition is NegativeCondition.Q_THRESHOLD:
            status["config"]["threshold_var"] = config.threshold_var
            status["config"]["q_direction"] = config.q_direction.value
        runtime = self._monitor_runtime.get(device_id)
        values = self._monitor_active_values.get(device_id, {})
        if runtime is not None:
            status["active_conditions"] = [
                {
                    "phase": key.phase.value,
                    "measurement": key.measurement.value,
                    "value": values.get(key),
                }
                for key in sorted(
                    runtime.active_keys,
                    key=lambda item: (item.phase.value, item.measurement.value),
                )
            ]
        return status

    def _disable_monitor_locked(self, device_id: str) -> None:
        super()._disable_monitor_locked(device_id)
        self._monitor_active_values.pop(device_id, None)

    def stop(self, device_id: str) -> None:
        with self._lock:
            self._require_commands_enabled()
            recorder = self._active.pop(device_id, None)
            if recorder is None:
                raise KeyError(device_id)
            self._active_owner.pop(device_id, None)
            recorder.stop()
            runtime = self._monitor_runtime.get(device_id)
            if runtime is not None:
                self._monitor_state[device_id] = (
                    MonitorOperationalState.WAITING_FOR_CLEAR
                    if runtime.active_keys
                    else MonitorOperationalState.WAITING
                )

    def _recording_failure_event(
        self,
        device_id: str,
        recorder: BaseSessionRecorder,
        cycle_id: int,
        error: Exception,
    ) -> DiagnosticEvent:
        event = super()._recording_failure_event(device_id, recorder, cycle_id, error)
        runtime = self._monitor_runtime.get(device_id)
        if runtime is not None:
            self._monitor_state[device_id] = (
                MonitorOperationalState.WAITING_FOR_CLEAR
                if runtime.active_keys
                else MonitorOperationalState.WAITING
            )
        return event

    def _monitor_event_detail(self, device_id: str, event: NegativeMonitorEvent) -> str:
        config = self._monitor_configs[device_id]
        if config.condition is NegativeCondition.Q_THRESHOLD:
            return (
                f"phase={event.phase.value};measurement={event.measurement.value};"
                f"value={repr(event.value)};threshold_var={repr(config.threshold_var)};"
                f"q_direction={config.q_direction.value};continuity={event.continuity}"
            )
        return (
            f"phase={event.phase.value};measurement={event.measurement.value};"
            f"value={repr(event.value)};threshold=0.0;continuity={event.continuity}"
        )

    def _remember_monitor_events(
        self,
        device_id: str,
        events: tuple[NegativeMonitorEvent, ...],
    ) -> None:
        for event in events:
            self._monitor_last_event[device_id] = {
                "event": event.name,
                "phase": event.phase.value,
                "measurement": event.measurement.value,
                "cycle_id": event.cycle_id,
                "utc": event.occurred_utc.isoformat(),
                "value": event.value,
                "continuity": event.continuity,
            }

    def _write_monitor_events(
        self,
        device_id: str,
        recorder: BaseSessionRecorder,
        events: tuple[NegativeMonitorEvent, ...],
    ) -> None:
        for event in events:
            recorder.record_event(
                event.occurred_utc,
                event.name,
                "INFO",
                event.cycle_id,
                self._monitor_event_detail(device_id, event),
            )

    def _start_monitor_recording(
        self,
        device_id: str,
        sample: MeasurementSample,
        evaluation: NegativeMonitorEvaluation,
    ) -> SessionRecorder:
        primary = evaluation.first_activation
        if primary is None:
            raise RuntimeError("monitor recording start requires activation evidence")
        config = self._monitor_configs[device_id]
        monitor_evidence = {
            "condition": config.condition.value,
            "phases": [phase.value for phase in config.phases],
            "start_phase": primary.phase.value,
            "start_measurement": primary.measurement.value,
            "start_event": primary.name,
            "start_cycle_id": primary.cycle_id,
            "start_utc": primary.occurred_utc.isoformat(),
            "start_value": primary.value,
        }
        if config.condition is NegativeCondition.Q_THRESHOLD:
            monitor_evidence["threshold_var"] = config.threshold_var
            monitor_evidence["q_direction"] = config.q_direction.value
        recorder = SessionRecorder.create(
            self._root,
            sample,
            self._devices[device_id],
            config.recording_interval_s,
            self._application_version,
            started_utc=primary.occurred_utc,
            monitor_evidence=monitor_evidence,
        )
        self._failed.pop(device_id, None)
        self._active[device_id] = recorder
        self._active_owner[device_id] = RecordingOwner.NEGATIVE_CONDITION_MONITOR
        self._monitor_state[device_id] = MonitorOperationalState.RECORDING
        self._write_monitor_events(device_id, recorder, evaluation.events)
        return recorder

    def _monitor_start_failure_event(
        self,
        device_id: str,
        sample: MeasurementSample,
        error: Exception,
    ) -> DiagnosticEvent:
        failed_utc = sample.timing.cycle_finished_utc
        config = self._monitor_configs[device_id]
        start_source = self._monitor_source(config)
        self._failed[device_id] = {
            "device_id": device_id,
            "device_name": self._devices[device_id].name,
            "state": "ERROR",
            "start_source": start_source,
            "session_id": "",
            "session_dir": "",
            "failed_utc": failed_utc.isoformat(),
            "failed_cycle_id": sample.identity.cycle_id,
            "error_type": type(error).__name__,
            "error_detail": str(error) or type(error).__name__,
        }
        event_name = (
            "Q_THRESHOLD_MONITOR_RECORDING_START_ERROR"
            if config.condition is NegativeCondition.Q_THRESHOLD
            else "NEGATIVE_MONITOR_RECORDING_START_ERROR"
        )
        return DiagnosticEvent(
            device_id=device_id,
            cycle_id=sample.identity.cycle_id,
            occurred_utc=failed_utc,
            event=event_name,
            severity=Severity.ERROR,
            detail=f"{type(error).__name__}: {str(error) or type(error).__name__}",
        )

    def _process_monitor_sample(
        self,
        sample: MeasurementSample,
    ) -> list[DiagnosticEvent]:
        with self._lock:
            device_id = sample.identity.device_id
            runtime = self._monitor_runtime.get(device_id)
            if runtime is None:
                return []

            previous_cycle_id = runtime.previous_cycle_id
            evaluation = evaluate_monitor_sample(runtime, sample)
            if runtime.previous_cycle_id == sample.identity.cycle_id and (
                previous_cycle_id != runtime.previous_cycle_id
                or previous_cycle_id is None
            ):
                self._monitor_active_values[device_id] = {
                    key: extract_condition_value(sample, key)
                    for key in runtime.active_keys
                }
            self._remember_monitor_events(device_id, evaluation.events)

            recorder = self._active.get(device_id)
            owner = self._active_owner.get(device_id)
            state = self._monitor_state.get(device_id, MonitorOperationalState.OFF)

            if recorder is not None:
                try:
                    self._write_monitor_events(device_id, recorder, evaluation.events)
                except Exception as exc:
                    return [
                        self._recording_failure_event(
                            device_id,
                            recorder,
                            sample.identity.cycle_id,
                            exc,
                        )
                    ]
                if evaluation.aggregate_active:
                    self._monitor_state[device_id] = MonitorOperationalState.RECORDING
                else:
                    self._monitor_state[device_id] = MonitorOperationalState.WAITING
                    if owner is RecordingOwner.NEGATIVE_CONDITION_MONITOR:
                        self._active.pop(device_id, None)
                        self._active_owner.pop(device_id, None)
                        recorder.stop(sample.timing.cycle_finished_utc)
                return []

            if state is MonitorOperationalState.WAITING_FOR_CLEAR:
                if not evaluation.aggregate_active:
                    self._monitor_state[device_id] = MonitorOperationalState.WAITING
                return []

            if (
                state is MonitorOperationalState.WAITING
                and evaluation.aggregate_active
                and evaluation.first_activation is not None
            ):
                try:
                    self._start_monitor_recording(device_id, sample, evaluation)
                except Exception as exc:
                    created_recorder = self._active.get(device_id)
                    if (
                        created_recorder is not None
                        and self._active_owner.get(device_id)
                        is RecordingOwner.NEGATIVE_CONDITION_MONITOR
                    ):
                        return [
                            self._recording_failure_event(
                                device_id,
                                created_recorder,
                                sample.identity.cycle_id,
                                exc,
                            )
                        ]
                    self._monitor_state[device_id] = (
                        MonitorOperationalState.WAITING_FOR_CLEAR
                        if evaluation.aggregate_active
                        else MonitorOperationalState.WAITING
                    )
                    return [self._monitor_start_failure_event(device_id, sample, exc)]
                return []

            if not evaluation.aggregate_active:
                self._monitor_state[device_id] = MonitorOperationalState.WAITING
            return []

    def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._subscriber.get(timeout=0.1)
            except Empty:
                continue

            failure_events: list[DiagnosticEvent] = []
            with self._lock:
                if isinstance(event, MeasurementSample):
                    device_id = event.identity.device_id
                    cycle_id = event.identity.cycle_id
                    recorder = self._active.get(device_id)
                    recording_failed = False
                    if recorder is not None:
                        try:
                            recorder.consider_sample(event)
                        except Exception as exc:
                            failure_events.append(
                                self._recording_failure_event(
                                    device_id,
                                    recorder,
                                    cycle_id,
                                    exc,
                                )
                            )
                            recording_failed = True
                    if not recording_failed and device_id in self._monitor_runtime:
                        failure_events.extend(self._process_monitor_sample(event))
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
                            failure_events.append(
                                self._recording_failure_event(
                                    device_id,
                                    recorder,
                                    event.cycle_id,
                                    exc,
                                )
                            )
                    runtime = self._monitor_runtime.get(device_id)
                    if runtime is not None:
                        invalidate_monitor_continuity(runtime, MonitorBoundary.GAP)

            for failure_event in failure_events:
                self._bus.publish(failure_event)


__all__ = [
    "MonitorOperationalState",
    "NegativeMonitorRecordingManager",
    "RecordingOwner",
    "SessionRecorder",
]
