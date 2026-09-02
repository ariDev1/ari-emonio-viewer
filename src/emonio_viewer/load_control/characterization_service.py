from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timezone
from enum import Enum
import math
from queue import Empty, Full, Queue
import uuid
from typing import Protocol

from emonio_viewer.config.model import DeviceConfig, RuntimeConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEvent, RuntimeEventBus

from .characterization import (
    ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT,
    ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT,
    CharacterizationPoint,
    build_characterization_point,
    validate_sweep_duties,
)
from .manual_pwm import ManualPwmStatus
from .stage3a import Stage3AError


CHARACTERIZATION_PWM_OWNER = "STAGE4B_CHARACTERIZATION"
SETTLING_CYCLES_PER_POINT = 2
MEASURED_CYCLES_PER_POINT = 3
_EVENT_QUEUE_WAIT_S = 0.05
_ACQUISITION_EVENT_PREFIX = "ACQUISITION_"


class CharacterizationState(str, Enum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    SWEEPING = "SWEEPING"
    SETTLING = "SETTLING"
    MEASURING = "MEASURING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    SAFE_UNCONFIRMED = "SAFE_UNCONFIRMED"


class Stage4BCharacterizationError(RuntimeError):
    """Raised when a Stage 4B characterization operation is not admissible."""


class _ManualPwmInterface(Protocol):
    @property
    def pwm_owner(self) -> str | None: ...

    def manual_pwm_status(self) -> ManualPwmStatus: ...

    def reserve_pwm_owner(self, owner: str) -> None: ...

    def release_pwm_owner(self, owner: str) -> None: ...

    async def run_reserved_pwm(
        self,
        duty_percent: float,
        *,
        owner: str,
    ) -> ManualPwmStatus: ...


@dataclass(frozen=True, slots=True)
class CharacterizationStatus:
    state: CharacterizationState
    session_id: str | None
    mode: str | None
    source_id: str | None
    phase: str | None
    point_index: int | None
    point_count: int | None
    current_requested_duty_percent: float | None
    settling_cycles_observed: int
    measured_cycles_observed: int
    points: tuple[CharacterizationPoint, ...]
    last_error: str | None
    safe_confirmed: bool | None


def _valid_poll_interval(value: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class Stage4BCharacterizationService:
    """Measure P response at explicit PWM duty points.

    The service observes existing canonical MeasurementSample events. It does
    not trigger acquisition, change measurement data, calculate a regulator
    output, or map watts to duty. All PWM commands use the existing qualified
    manual PWM service and its single sequence/ACK path.
    """

    def __init__(
        self,
        bus: RuntimeEventBus,
        config: RuntimeConfig,
        *,
        manual_pwm: _ManualPwmInterface,
    ) -> None:
        if not isinstance(bus, RuntimeEventBus):
            raise ValueError("bus must be RuntimeEventBus")
        if not isinstance(config, RuntimeConfig):
            raise ValueError("config must be RuntimeConfig")
        for name in (
            "manual_pwm_status",
            "reserve_pwm_owner",
            "release_pwm_owner",
            "run_reserved_pwm",
        ):
            if not callable(getattr(manual_pwm, name, None)):
                raise ValueError(f"manual_pwm must provide {name}")

        self._bus = bus
        self._config = config
        self._manual_pwm = manual_pwm
        self._subscriber: Queue[RuntimeEvent] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._runtime_queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=256)
        self._stop_sentinel = object()
        self._started = False
        self._active = False
        self._latest_cycle_by_source: dict[str, int] = {}

        self._state = CharacterizationState.IDLE
        self._session_id: str | None = None
        self._mode: str | None = None
        self._source_id: str | None = None
        self._phase: str | None = None
        self._point_index: int | None = None
        self._point_count: int | None = None
        self._current_requested_duty: float | None = None
        self._settling_cycles_observed = 0
        self._measured_cycles_observed = 0
        self._points: list[CharacterizationPoint] = []
        self._last_error: str | None = None
        self._safe_confirmed: bool | None = None

    def status(self) -> CharacterizationStatus:
        return CharacterizationStatus(
            state=self._state,
            session_id=self._session_id,
            mode=self._mode,
            source_id=self._source_id,
            phase=self._phase,
            point_index=self._point_index,
            point_count=self._point_count,
            current_requested_duty_percent=self._current_requested_duty,
            settling_cycles_observed=self._settling_cycles_observed,
            measured_cycles_observed=self._measured_cycles_observed,
            points=tuple(self._points),
            last_error=self._last_error,
            safe_confirmed=self._safe_confirmed,
        )

    def _source_config(self, source_id: str) -> DeviceConfig | None:
        matches = tuple(
            item
            for item in self._config.devices
            if item.enabled
            and item.id == source_id
            and _valid_poll_interval(item.poll_interval_s)
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _validate_phase(phase: str) -> str:
        if phase not in {"A", "B", "C"}:
            raise Stage4BCharacterizationError("PHASE_NOT_SELECTED")
        return phase

    @staticmethod
    def _phase_p(sample: MeasurementSample, phase: str) -> float:
        if phase == "A":
            value = sample.phase_a.measurement.p
        elif phase == "B":
            value = sample.phase_b.measurement.p
        else:
            value = sample.phase_c.measurement.p
        result = _finite(value)
        if result is None:
            raise Stage4BCharacterizationError("SAMPLE_INVALID")
        return result

    def _reset_session(
        self,
        *,
        mode: str,
        source_id: str,
        phase: str,
        point_count: int,
    ) -> None:
        self._session_id = uuid.uuid4().hex
        self._mode = mode
        self._source_id = source_id
        self._phase = phase
        self._point_index = None
        self._point_count = point_count
        self._current_requested_duty = None
        self._settling_cycles_observed = 0
        self._measured_cycles_observed = 0
        self._points = []
        self._last_error = None
        self._safe_confirmed = None

    async def start(self) -> None:
        if self._started:
            return
        self._subscriber = self._bus.subscribe(maxsize=256)
        self._started = True
        self._consumer_task = asyncio.create_task(self._consume_events())

    def _queue_private(self, item: object) -> None:
        subscriber = self._subscriber
        if subscriber is None:
            return
        while True:
            try:
                subscriber.put_nowait(item)  # type: ignore[arg-type]
                return
            except Full:
                try:
                    subscriber.get_nowait()
                except Exception:
                    return

    async def close(self) -> None:
        if self._active:
            raise Stage4BCharacterizationError("CHARACTERIZATION_ACTIVE")
        if self._started:
            self._queue_private(self._stop_sentinel)
            if self._consumer_task is not None:
                await self._consumer_task
            if self._subscriber is not None:
                self._bus.unsubscribe(self._subscriber)
        self._subscriber = None
        self._consumer_task = None
        self._started = False
        self._drain_runtime_queue()

    async def _consume_events(self) -> None:
        assert self._subscriber is not None
        while True:
            try:
                item = await asyncio.to_thread(
                    self._subscriber.get,
                    True,
                    _EVENT_QUEUE_WAIT_S,
                )
            except Empty:
                continue
            if item is self._stop_sentinel:
                return
            if isinstance(item, MeasurementSample):
                source_id = item.identity.device_id
                cycle_id = item.identity.cycle_id
                previous = self._latest_cycle_by_source.get(source_id, 0)
                if cycle_id > previous:
                    self._latest_cycle_by_source[source_id] = cycle_id
            self._put_runtime_event(item)

    def _put_runtime_event(self, event: RuntimeEvent) -> None:
        while self._runtime_queue.full():
            try:
                self._runtime_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._runtime_queue.put_nowait(event)

    def _drain_runtime_queue(self) -> None:
        while True:
            try:
                self._runtime_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def _next_sample(
        self,
        *,
        source: DeviceConfig,
        boundary_cycle: int,
        expected_cycle: int,
    ) -> MeasurementSample:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 2.0 * float(source.poll_interval_s)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0.0:
                raise Stage4BCharacterizationError("SAMPLE_STALE")
            try:
                event = await asyncio.wait_for(self._runtime_queue.get(), remaining)
            except asyncio.TimeoutError as exc:
                raise Stage4BCharacterizationError("SAMPLE_STALE") from exc

            if isinstance(event, DiagnosticEvent):
                if (
                    event.device_id == source.id
                    and event.cycle_id > boundary_cycle
                    and event.event.startswith(_ACQUISITION_EVENT_PREFIX)
                ):
                    raise Stage4BCharacterizationError("ACQUISITION_FAILURE")
                continue

            if not isinstance(event, MeasurementSample):
                continue
            if event.identity.device_id != source.id:
                continue
            cycle_id = event.identity.cycle_id
            if cycle_id <= boundary_cycle:
                continue
            if cycle_id != expected_cycle:
                raise Stage4BCharacterizationError("SAMPLE_SEQUENCE_GAP")
            if event.quality is not SampleQuality.VALID:
                raise Stage4BCharacterizationError("SAMPLE_INVALID")
            return event

    @staticmethod
    def _qualified_active_pwm(
        status: ManualPwmStatus,
        *,
        expected_requested: float | None = None,
    ) -> ManualPwmStatus:
        requested = _finite(status.requested_duty_percent)
        actual = _finite(status.actual_duty_percent)
        if (
            status.ack_result != "APPLIED"
            or status.node_id is None
            or status.boot_id is None
            or status.command_sequence is None
            or requested is None
            or actual is None
        ):
            raise Stage4BCharacterizationError("PWM_ACK_NOT_QUALIFIED")
        if expected_requested is not None and requested != expected_requested:
            raise Stage4BCharacterizationError("PWM_ACK_REQUESTED_DUTY_MISMATCH")
        if not (
            ACTIVE_CHARACTERIZATION_DUTY_MIN_PERCENT
            <= requested
            <= ACTIVE_CHARACTERIZATION_DUTY_MAX_PERCENT
        ):
            raise Stage4BCharacterizationError("PWM_DUTY_OUTSIDE_CHARACTERIZATION_RANGE")
        if actual <= 0.0 or actual >= 100.0:
            raise Stage4BCharacterizationError("PWM_ACK_ACTUAL_DUTY_INVALID")
        return status

    @staticmethod
    def _safe_off_confirmed(status: ManualPwmStatus) -> bool:
        return bool(
            status.ack_result == "APPLIED"
            and status.requested_duty_percent == 0.0
            and status.actual_duty_percent == 0.0
            and status.compare_ticks == 0
        )

    async def _collect_point(
        self,
        *,
        source: DeviceConfig,
        phase: str,
        pwm_status: ManualPwmStatus,
    ) -> CharacterizationPoint:
        requested = float(pwm_status.requested_duty_percent)  # qualified by caller
        actual = float(pwm_status.actual_duty_percent)  # qualified by caller
        boundary = self._latest_cycle_by_source.get(source.id, 0)
        expected = boundary + 1
        measured_cycles: list[int] = []
        measured_p: list[float] = []
        last_sample: MeasurementSample | None = None
        self._settling_cycles_observed = 0
        self._measured_cycles_observed = 0

        for index in range(SETTLING_CYCLES_PER_POINT + MEASURED_CYCLES_PER_POINT):
            self._state = (
                CharacterizationState.SETTLING
                if index < SETTLING_CYCLES_PER_POINT
                else CharacterizationState.MEASURING
            )
            sample = await self._next_sample(
                source=source,
                boundary_cycle=boundary,
                expected_cycle=expected,
            )
            expected += 1
            last_sample = sample
            if index < SETTLING_CYCLES_PER_POINT:
                self._settling_cycles_observed += 1
                continue
            measured_cycles.append(sample.identity.cycle_id)
            measured_p.append(self._phase_p(sample, phase))
            self._measured_cycles_observed += 1

        assert last_sample is not None
        assert self._session_id is not None
        assert self._mode is not None
        assert pwm_status.node_id is not None
        assert pwm_status.boot_id is not None
        assert pwm_status.command_sequence is not None
        point = build_characterization_point(
            session_id=self._session_id,
            mode=self._mode,
            source_id=source.id,
            phase=phase,
            actuator_node_id=pwm_status.node_id,
            actuator_boot_id=pwm_status.boot_id,
            command_sequence=pwm_status.command_sequence,
            requested_duty_percent=requested,
            actual_duty_percent=actual,
            cycle_ids=tuple(measured_cycles),
            p_samples_w=tuple(measured_p),
            utc=last_sample.timing.cycle_finished_utc.astimezone(timezone.utc).isoformat(),
        )
        return point

    async def _finish_safe(self) -> bool:
        try:
            status = await self._manual_pwm.run_reserved_pwm(
                0.0,
                owner=CHARACTERIZATION_PWM_OWNER,
            )
        except Exception:
            return False
        return self._safe_off_confirmed(status)

    async def _run_session(
        self,
        *,
        mode: str,
        source_id: str,
        phase: str,
        duties: tuple[float, ...] | None,
    ) -> CharacterizationStatus:
        if not self._started:
            raise Stage4BCharacterizationError("CHARACTERIZATION_NOT_STARTED")
        if self._active:
            raise Stage4BCharacterizationError("CHARACTERIZATION_ACTIVE")
        source = self._source_config(source_id)
        if source is None:
            raise Stage4BCharacterizationError("SOURCE_NOT_AVAILABLE")
        phase = self._validate_phase(phase)

        if mode == "AUTO_SWEEP":
            assert duties is not None
            try:
                sweep = validate_sweep_duties(duties)
            except ValueError as exc:
                raise Stage4BCharacterizationError("SWEEP_DUTIES_INVALID") from exc
            point_count = len(sweep)
        else:
            sweep = ()
            point_count = 1

        self._reset_session(
            mode=mode,
            source_id=source.id,
            phase=phase,
            point_count=point_count,
        )
        self._active = True
        reserved = False
        operation_error: str | None = None
        try:
            if mode == "MANUAL_CAPTURE":
                initial = self._qualified_active_pwm(self._manual_pwm.manual_pwm_status())

            try:
                self._manual_pwm.reserve_pwm_owner(CHARACTERIZATION_PWM_OWNER)
            except Stage3AError as exc:
                raise Stage4BCharacterizationError(str(exc)) from exc
            reserved = True
            self._drain_runtime_queue()

            if mode == "MANUAL_CAPTURE":
                self._state = CharacterizationState.CAPTURING
                self._point_index = 1
                assert initial.requested_duty_percent is not None
                self._current_requested_duty = float(initial.requested_duty_percent)
                point = await self._collect_point(
                    source=source,
                    phase=phase,
                    pwm_status=initial,
                )
                self._points.append(point)
            else:
                for point_index, duty in enumerate(sweep, start=1):
                    self._state = CharacterizationState.SWEEPING
                    self._point_index = point_index
                    self._current_requested_duty = duty
                    try:
                        applied = await self._manual_pwm.run_reserved_pwm(
                            duty,
                            owner=CHARACTERIZATION_PWM_OWNER,
                        )
                    except Stage3AError as exc:
                        raise Stage4BCharacterizationError(str(exc)) from exc
                    applied = self._qualified_active_pwm(
                        applied,
                        expected_requested=duty,
                    )
                    point = await self._collect_point(
                        source=source,
                        phase=phase,
                        pwm_status=applied,
                    )
                    self._points.append(point)
        except Stage4BCharacterizationError as exc:
            operation_error = str(exc)
        except Exception:
            operation_error = "CHARACTERIZATION_INTERNAL_ERROR"
        finally:
            if reserved:
                safe = await self._finish_safe()
                self._safe_confirmed = safe
                try:
                    self._manual_pwm.release_pwm_owner(CHARACTERIZATION_PWM_OWNER)
                except Exception:
                    safe = False
                    self._safe_confirmed = False
                if not safe:
                    self._state = CharacterizationState.SAFE_UNCONFIRMED
                    self._last_error = "SAFE_OFF_UNCONFIRMED"
                elif operation_error is not None:
                    self._state = CharacterizationState.ABORTED
                    self._last_error = operation_error
                else:
                    self._state = CharacterizationState.COMPLETED
                    self._last_error = None
            else:
                self._safe_confirmed = None
                self._state = CharacterizationState.ABORTED
                self._last_error = operation_error or "CHARACTERIZATION_NOT_STARTED"
            self._active = False
            self._current_requested_duty = None

        return self.status()

    async def capture_manual(
        self,
        *,
        source_id: str,
        phase: str,
    ) -> CharacterizationStatus:
        return await self._run_session(
            mode="MANUAL_CAPTURE",
            source_id=source_id,
            phase=phase,
            duties=None,
        )

    async def run_auto_sweep(
        self,
        *,
        source_id: str,
        phase: str,
        duties: tuple[float, ...],
    ) -> CharacterizationStatus:
        return await self._run_session(
            mode="AUTO_SWEEP",
            source_id=source_id,
            phase=phase,
            duties=duties,
        )
