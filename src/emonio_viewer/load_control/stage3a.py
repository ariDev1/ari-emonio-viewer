from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from queue import Empty, Full, Queue
import time
import uuid
from typing import Callable

from emonio_viewer.config.model import DeviceConfig, RuntimeConfig
from emonio_viewer.measurement.model import MeasurementSample, SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEvent, RuntimeEventBus

from .diagnostic_log import LoadControlDiagnosticLog
from .model import ThreePhasePower
from .protocol import (
    AckFrame,
    CommandFrame,
    HelloFrame,
    LOAD_CONTROL_PROTOCOL_VERSION,
    ProtocolError,
    StatusFrame,
)
from .qualified_channel import QualifiedActuatorChannel, QualifiedActuatorChannelError


ACK_TIMEOUT_S = 2.0
ZERO_POWER = ThreePhasePower(0.0, 0.0, 0.0)
_ACQUISITION_EVENT_PREFIX = "ACQUISITION_"
_EVENT_QUEUE_WAIT_S = 0.05


class Stage3AState(str, Enum):
    IDLE = "IDLE"
    SOURCE_SELECTED = "SOURCE_SELECTED"
    READY = "READY"
    WAITING_FOR_SAMPLE = "WAITING_FOR_SAMPLE"
    COMMAND_SENT = "COMMAND_SENT"
    WAITING_FOR_ACK = "WAITING_FOR_ACK"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Stage3AStatus:
    state: Stage3AState
    selected_source_id: str | None
    sample_cycle_id: int | None
    command_sequence: int | None
    ack_result: str | None
    rejection_reason: str | None
    admissible: bool


class Stage3AError(RuntimeError):
    """Raised when an operator Stage-3A request is not admissible."""


class _SourceAcquisitionFailure(RuntimeError):
    pass


class _ActuatorDisconnected(RuntimeError):
    pass


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__


def _valid_poll_interval(value: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _aware_iso(moment: datetime, name: str) -> str:
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat()


class Stage3ASafeCommandService:
    """Qualify one explicit zero-output COMMAND/ACK exchange.

    This service observes existing canonical samples. It does not trigger
    acquisition, calculate a nonzero demand, persist a source binding, retry a
    command, or enable real control.
    """

    def __init__(
        self,
        bus: RuntimeEventBus,
        config: RuntimeConfig,
        qualified_channel: QualifiedActuatorChannel,
        *,
        diagnostic_log: LoadControlDiagnosticLog | None = None,
        viewer_session_id: str | None = None,
        utc_now: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
        wait_for=asyncio.wait_for,
    ) -> None:
        if not isinstance(bus, RuntimeEventBus):
            raise ValueError("bus must be RuntimeEventBus")
        if not isinstance(config, RuntimeConfig):
            raise ValueError("config must be RuntimeConfig")
        self._bus = bus
        self._config = config
        self._channel = qualified_channel
        self._diagnostic_log = diagnostic_log or LoadControlDiagnosticLog()
        self._viewer_session_id = viewer_session_id or uuid.uuid4().hex
        if not isinstance(self._viewer_session_id, str) or not self._viewer_session_id:
            raise ValueError("viewer_session_id must be non-empty text")
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._wait_for = wait_for

        self._subscriber: Queue[RuntimeEvent] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._stop_sentinel = object()
        self._started = False

        self._selected_source_id: str | None = None
        self._latest_cycle_by_source: dict[str, int] = {}
        self._state = Stage3AState.IDLE
        self._sample_cycle_id: int | None = None
        self._command_sequence: int | None = None
        self._ack_result: str | None = None
        self._rejection_reason: str | None = None
        self._next_sequence = 1
        self._active = False
        self._ack_wait_active = False

        self._sample_waiter: asyncio.Future[MeasurementSample] | None = None
        self._sample_source_id: str | None = None
        self._sample_boundary_cycle = 0
        self._sample_request_monotonic_ns = 0

    @property
    def diagnostic_log(self) -> LoadControlDiagnosticLog:
        return self._diagnostic_log

    @property
    def viewer_session_id(self) -> str:
        return self._viewer_session_id

    def sources(self) -> tuple[DeviceConfig, ...]:
        return tuple(device for device in self._config.devices if device.enabled)

    def _source_config(self, device_id: str | None) -> DeviceConfig | None:
        if device_id is None:
            return None
        matches = tuple(
            device
            for device in self._config.devices
            if device.enabled and device.id == device_id
        )
        if len(matches) != 1:
            return None
        return matches[0]

    def status(self) -> Stage3AStatus:
        state = self._state
        if (
            not self._active
            and self._selected_source_id is not None
            and state in {Stage3AState.SOURCE_SELECTED, Stage3AState.READY}
        ):
            state = (
                Stage3AState.READY
                if self._channel.hello() is not None
                else Stage3AState.SOURCE_SELECTED
            )
        admissible = bool(
            self._started
            and not self._active
            and self._source_config(self._selected_source_id) is not None
            and self._channel.hello() is not None
        )
        return Stage3AStatus(
            state=state,
            selected_source_id=self._selected_source_id,
            sample_cycle_id=self._sample_cycle_id,
            command_sequence=self._command_sequence,
            ack_result=self._ack_result,
            rejection_reason=self._rejection_reason,
            admissible=admissible,
        )

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
        if not self._started:
            self._selected_source_id = None
            self._state = Stage3AState.IDLE
            return
        waiter = self._sample_waiter
        if waiter is not None and not waiter.done():
            waiter.set_exception(Stage3AError("STAGE3A_SERVICE_CLOSED"))
        self._queue_private(self._stop_sentinel)
        if self._consumer_task is not None:
            await self._consumer_task
        if self._subscriber is not None:
            self._bus.unsubscribe(self._subscriber)
        self._subscriber = None
        self._consumer_task = None
        self._sample_waiter = None
        self._sample_source_id = None
        self._selected_source_id = None
        self._active = False
        self._ack_wait_active = False
        self._started = False
        self._state = Stage3AState.IDLE

    def _log_status(self, frame: StatusFrame) -> None:
        self._diagnostic_log.append(
            "SAFE_STATUS_RECEIVED",
            node_id=frame.node_id,
            boot_id=frame.boot_id,
            state=frame.state,
            applied_p_a_w=frame.applied_p.a,
            applied_p_b_w=frame.applied_p.b,
            applied_p_c_w=frame.applied_p.c,
        )

    def _log_unexpected_ack(self, frame: AckFrame) -> None:
        self._diagnostic_log.append(
            "SAFE_ACK_UNEXPECTED",
            node_id=frame.node_id,
            boot_id=frame.boot_id,
            viewer_session_id=frame.viewer_session_id,
            sequence=frame.sequence,
            result=frame.result,
            applied_p_a_w=frame.applied_p.a,
            applied_p_b_w=frame.applied_p.b,
            applied_p_c_w=frame.applied_p.c,
        )

    def _drain_unsolicited_actuator_frames(self) -> None:
        if self._ack_wait_active or self._channel.hello() is None:
            return
        while True:
            try:
                frame = self._channel.receive_nowait()
            except asyncio.QueueEmpty:
                return
            except (ConnectionError, QualifiedActuatorChannelError, ProtocolError):
                return
            except Exception:
                return
            if isinstance(frame, AckFrame):
                self._log_unexpected_ack(frame)
            elif isinstance(frame, StatusFrame):
                self._log_status(frame)

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
                self._drain_unsolicited_actuator_frames()
                continue
            if item is self._stop_sentinel:
                return
            self._handle_runtime_event(item)
            self._drain_unsolicited_actuator_frames()

    def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, MeasurementSample):
            device_id = event.identity.device_id
            cycle_id = event.identity.cycle_id
            previous = self._latest_cycle_by_source.get(device_id, 0)
            if cycle_id > previous:
                self._latest_cycle_by_source[device_id] = cycle_id
            waiter = self._sample_waiter
            if (
                waiter is not None
                and not waiter.done()
                and device_id == self._sample_source_id
                and cycle_id > self._sample_boundary_cycle
                and event.timing.cycle_started_monotonic_ns > self._sample_request_monotonic_ns
                and event.quality is SampleQuality.VALID
            ):
                waiter.set_result(event)
            return

        if isinstance(event, DiagnosticEvent):
            waiter = self._sample_waiter
            if (
                waiter is not None
                and not waiter.done()
                and event.device_id == self._sample_source_id
                and event.cycle_id > self._sample_boundary_cycle
                and event.event.startswith(_ACQUISITION_EVENT_PREFIX)
            ):
                waiter.set_exception(_SourceAcquisitionFailure(event.event))

    async def select_source(self, device_id: str) -> Stage3AStatus:
        if self._active:
            raise Stage3AError("SAFE_TEST_ACTIVE")
        if not isinstance(device_id, str) or not device_id:
            raise Stage3AError("SOURCE_NOT_AVAILABLE")
        source = self._source_config(device_id)
        if source is None or not _valid_poll_interval(source.poll_interval_s):
            raise Stage3AError("SOURCE_NOT_AVAILABLE")
        self._selected_source_id = source.id
        self._sample_cycle_id = None
        self._command_sequence = None
        self._ack_result = None
        self._rejection_reason = None
        self._state = (
            Stage3AState.READY
            if self._channel.hello() is not None
            else Stage3AState.SOURCE_SELECTED
        )
        self._diagnostic_log.append(
            "SAFE_SOURCE_SELECTED",
            emonio_device_id=source.id,
            poll_interval_s=float(source.poll_interval_s),
        )
        return self.status()

    def _reject(self, reason: str) -> Stage3AStatus:
        self._state = Stage3AState.REJECTED
        self._rejection_reason = reason
        self._diagnostic_log.append(
            "SAFE_TEST_REJECTED",
            reason=reason,
            emonio_device_id=self._selected_source_id,
            sequence=self._command_sequence,
        )
        return self.status()

    def _reject_and_raise(self, reason: str) -> None:
        self._reject(reason)
        raise Stage3AError(reason)

    async def _sample_or_disconnect(
        self,
        waiter: asyncio.Future[MeasurementSample],
        disconnect_event: asyncio.Event,
    ) -> MeasurementSample:
        disconnect_task = asyncio.create_task(disconnect_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {waiter, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done:
                raise _ActuatorDisconnected()
            return waiter.result()
        finally:
            if not disconnect_task.done():
                disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task

    async def _next_valid_sample(
        self,
        *,
        source: DeviceConfig,
        boundary_cycle: int,
        request_monotonic_ns: int,
    ) -> MeasurementSample | None:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[MeasurementSample] = loop.create_future()
        self._sample_waiter = waiter
        self._sample_source_id = source.id
        self._sample_boundary_cycle = boundary_cycle
        self._sample_request_monotonic_ns = request_monotonic_ns
        combined_task = asyncio.create_task(
            self._sample_or_disconnect(waiter, self._channel.disconnect_event())
        )
        try:
            return await self._wait_for(
                combined_task,
                2.0 * float(source.poll_interval_s),
            )
        except asyncio.TimeoutError:
            return None
        finally:
            if not combined_task.done():
                combined_task.cancel()
            with suppress(asyncio.CancelledError):
                await combined_task
            if not waiter.done():
                waiter.cancel()
            self._sample_waiter = None
            self._sample_source_id = None
            self._sample_boundary_cycle = 0
            self._sample_request_monotonic_ns = 0

    def _build_command(
        self,
        *,
        hello: HelloFrame,
        source: DeviceConfig,
        sample: MeasurementSample,
        sequence: int,
    ) -> CommandFrame:
        return CommandFrame(
            protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
            viewer_session_id=self._viewer_session_id,
            node_id=hello.node_id,
            boot_id=hello.boot_id,
            sequence=sequence,
            emonio_device_id=source.id,
            measurement_cycle_id=sample.identity.cycle_id,
            measurement_utc=_aware_iso(sample.timing.cycle_finished_utc, "measurement_utc"),
            command_utc=_aware_iso(self._utc_now(), "command_utc"),
            control_enabled=False,
            p_reserve=0.0,
            measured_p=ThreePhasePower(
                sample.phase_a.measurement.p,
                sample.phase_b.measurement.p,
                sample.phase_c.measurement.p,
            ),
            measured_q=ThreePhasePower(
                sample.phase_a.measurement.q,
                sample.phase_b.measurement.q,
                sample.phase_c.measurement.q,
            ),
            p_load_request=ZERO_POWER,
            q_comp_request=ZERO_POWER,
        )

    @staticmethod
    def _ack_mismatch(command: CommandFrame, ack: AckFrame) -> str | None:
        if ack.protocol_version != LOAD_CONTROL_PROTOCOL_VERSION:
            return "ACK_PROTOCOL_MISMATCH"
        if ack.viewer_session_id != command.viewer_session_id:
            return "ACK_SESSION_MISMATCH"
        if ack.node_id != command.node_id:
            return "ACK_NODE_MISMATCH"
        if ack.boot_id != command.boot_id:
            return "ACK_BOOT_MISMATCH"
        if ack.sequence != command.sequence:
            return "ACK_SEQUENCE_MISMATCH"
        if ack.result != "APPLIED":
            return "ACK_RESULT_MISMATCH"
        if ack.applied_p != ZERO_POWER:
            return "ACK_APPLIED_P_MISMATCH"
        return None

    async def _wait_for_ack(self, command: CommandFrame) -> Stage3AStatus:
        deadline_ns = self._monotonic_ns() + int(ACK_TIMEOUT_S * 1_000_000_000)
        self._state = Stage3AState.WAITING_FOR_ACK
        while True:
            remaining_s = (deadline_ns - self._monotonic_ns()) / 1_000_000_000.0
            if remaining_s <= 0.0:
                return self._reject("ACK_TIMEOUT")
            try:
                frame = await self._channel.receive(remaining_s)
            except asyncio.TimeoutError:
                return self._reject("ACK_TIMEOUT")
            except (ConnectionError, QualifiedActuatorChannelError):
                return self._reject("ACTUATOR_DISCONNECTED")
            except ProtocolError as exc:
                if "unsupported protocol_version" in _error_text(exc):
                    return self._reject("ACK_PROTOCOL_MISMATCH")
                return self._reject("UNEXPECTED_ACTUATOR_FRAME")
            except Exception:
                return self._reject("UNEXPECTED_ACTUATOR_FRAME")

            if isinstance(frame, StatusFrame):
                self._log_status(frame)
                continue
            if not isinstance(frame, AckFrame):
                return self._reject("UNEXPECTED_ACTUATOR_FRAME")

            if (
                frame.viewer_session_id == command.viewer_session_id
                and frame.sequence < command.sequence
            ):
                self._log_unexpected_ack(frame)
                continue

            self._diagnostic_log.append(
                "SAFE_ACK_RECEIVED",
                node_id=frame.node_id,
                boot_id=frame.boot_id,
                viewer_session_id=frame.viewer_session_id,
                sequence=frame.sequence,
                result=frame.result,
                applied_p_a_w=frame.applied_p.a,
                applied_p_b_w=frame.applied_p.b,
                applied_p_c_w=frame.applied_p.c,
            )
            mismatch = self._ack_mismatch(command, frame)
            if mismatch is not None:
                return self._reject(mismatch)

            self._ack_result = frame.result
            self._diagnostic_log.append(
                "SAFE_ACK_QUALIFIED",
                sequence=frame.sequence,
                result=frame.result,
                applied_p_a_w=frame.applied_p.a,
                applied_p_b_w=frame.applied_p.b,
                applied_p_c_w=frame.applied_p.c,
            )
            self._state = Stage3AState.PASSED
            self._rejection_reason = None
            self._diagnostic_log.append(
                "SAFE_TEST_PASSED",
                emonio_device_id=self._selected_source_id,
                sequence=frame.sequence,
                node_id=frame.node_id,
                boot_id=frame.boot_id,
            )
            return self.status()

    async def run_safe_test(self) -> Stage3AStatus:
        if self._active:
            raise Stage3AError("SAFE_TEST_ACTIVE")
        self._active = True
        try:
            if not self._started:
                self._reject_and_raise("SOURCE_NOT_AVAILABLE")
            source = self._source_config(self._selected_source_id)
            if source is None:
                self._reject_and_raise(
                    "SOURCE_NOT_SELECTED"
                    if self._selected_source_id is None
                    else "SOURCE_NOT_AVAILABLE"
                )
            assert source is not None
            if not _valid_poll_interval(source.poll_interval_s):
                self._reject_and_raise("SOURCE_NOT_AVAILABLE")
            hello = self._channel.hello()
            if hello is None:
                self._reject_and_raise("ACTUATOR_NOT_QUALIFIED")
            assert hello is not None

            self._drain_unsolicited_actuator_frames()
            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject("ACTUATOR_DISCONNECTED")

            self._sample_cycle_id = None
            self._command_sequence = None
            self._ack_result = None
            self._rejection_reason = None
            boundary_cycle = self._latest_cycle_by_source.get(source.id, 0)
            request_monotonic_ns = self._monotonic_ns()
            self._diagnostic_log.append(
                "SAFE_TEST_REQUESTED",
                emonio_device_id=source.id,
                node_id=hello.node_id,
                boot_id=hello.boot_id,
                boundary_cycle_id=boundary_cycle,
            )
            self._state = Stage3AState.WAITING_FOR_SAMPLE
            self._diagnostic_log.append(
                "SAFE_SAMPLE_WAIT_STARTED",
                emonio_device_id=source.id,
                boundary_cycle_id=boundary_cycle,
                timeout_s=2.0 * float(source.poll_interval_s),
            )

            try:
                sample = await self._next_valid_sample(
                    source=source,
                    boundary_cycle=boundary_cycle,
                    request_monotonic_ns=request_monotonic_ns,
                )
            except _SourceAcquisitionFailure:
                return self._reject("SOURCE_ACQUISITION_FAILURE")
            except _ActuatorDisconnected:
                return self._reject("ACTUATOR_DISCONNECTED")
            if sample is None:
                return self._reject("NO_NEW_VALID_SAMPLE")

            self._sample_cycle_id = sample.identity.cycle_id
            measured_p = ThreePhasePower(
                sample.phase_a.measurement.p,
                sample.phase_b.measurement.p,
                sample.phase_c.measurement.p,
            )
            measured_q = ThreePhasePower(
                sample.phase_a.measurement.q,
                sample.phase_b.measurement.q,
                sample.phase_c.measurement.q,
            )
            self._diagnostic_log.append(
                "SAFE_SAMPLE_ACCEPTED",
                emonio_device_id=source.id,
                measurement_cycle_id=sample.identity.cycle_id,
                measurement_utc=_aware_iso(sample.timing.cycle_finished_utc, "measurement_utc"),
                measured_p_a_w=measured_p.a,
                measured_p_b_w=measured_p.b,
                measured_p_c_w=measured_p.c,
                measured_q_a_var=measured_q.a,
                measured_q_b_var=measured_q.b,
                measured_q_c_var=measured_q.c,
            )

            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject("ACTUATOR_DISCONNECTED")

            self._drain_unsolicited_actuator_frames()
            current_hello = self._channel.hello()
            if (
                current_hello is None
                or current_hello.node_id != hello.node_id
                or current_hello.boot_id != hello.boot_id
            ):
                return self._reject("ACTUATOR_DISCONNECTED")

            sequence = self._next_sequence
            self._next_sequence += 1
            self._command_sequence = sequence
            command = self._build_command(
                hello=hello,
                source=source,
                sample=sample,
                sequence=sequence,
            )
            self._ack_wait_active = True
            try:
                try:
                    await self._channel.send(command)
                except (ConnectionError, QualifiedActuatorChannelError):
                    return self._reject("ACTUATOR_DISCONNECTED")
                except Exception:
                    return self._reject("COMMAND_SEND_FAILED")

                self._state = Stage3AState.COMMAND_SENT
                self._diagnostic_log.append(
                    "SAFE_COMMAND_SENT",
                    emonio_device_id=source.id,
                    measurement_cycle_id=sample.identity.cycle_id,
                    viewer_session_id=command.viewer_session_id,
                    node_id=command.node_id,
                    boot_id=command.boot_id,
                    sequence=command.sequence,
                    control_enabled=command.control_enabled,
                    requested_p_a_w=command.p_load_request.a,
                    requested_p_b_w=command.p_load_request.b,
                    requested_p_c_w=command.p_load_request.c,
                )
                return await self._wait_for_ack(command)
            finally:
                self._ack_wait_active = False
        finally:
            self._active = False
