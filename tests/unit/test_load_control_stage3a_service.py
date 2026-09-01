import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.diagnostic_log import LoadControlDiagnosticLog
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import AckFrame, HelloFrame, ProtocolError, StatusFrame
from emonio_viewer.load_control.stage3a import (
    Stage3AError,
    Stage3ASafeCommandService,
    Stage3AState,
)
from emonio_viewer.measurement.model import SampleQuality
from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity


ZERO = ThreePhasePower(0.0, 0.0, 0.0)


class FakeClock:
    def __init__(self, *, monotonic_ns: int = 10_000_000_000) -> None:
        self.monotonic_ns_value = monotonic_ns
        self.utc_value = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)

    def monotonic_ns(self) -> int:
        return self.monotonic_ns_value

    def utc_now(self) -> datetime:
        return self.utc_value

    def advance(self, seconds: float) -> None:
        self.monotonic_ns_value += int(seconds * 1_000_000_000)


class FakeQualifiedChannel:
    def __init__(self, hello: HelloFrame | None = None, *, clock: FakeClock | None = None) -> None:
        self.current_hello = hello
        self.sent = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self.receive_timeouts = []
        self.send_error: Exception | None = None
        self.clock = clock
        self.advance_on_receive_s = 0.0

    def hello(self) -> HelloFrame | None:
        return self.current_hello

    async def send(self, command) -> None:
        self.sent.append(command)
        if self.send_error is not None:
            raise self.send_error

    async def receive(self, timeout_s: float):
        self.receive_timeouts.append(timeout_s)
        if self.clock is not None and self.advance_on_receive_s:
            self.clock.advance(self.advance_on_receive_s)
        item = await asyncio.wait_for(self.frames.get(), timeout_s)
        if isinstance(item, Exception):
            raise item
        return item

    def push(self, item: object) -> None:
        self.frames.put_nowait(item)


def _hello(boot_id: str = "BOOT-STAGE3A-001") -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id=boot_id,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _config(*, poll_interval_s: float = 0.05, enabled: bool = True) -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(
            DeviceConfig(
                id="emonio-example",
                name="Emonio Example",
                host="192.0.2.11",
                port=502,
                unit_id=1,
                poll_interval_s=poll_interval_s,
                timeout_s=0.1,
                enabled=enabled,
                firmware_version="3.0.79-release",
            ),
        ),
    )


def _diagnostic_log() -> LoadControlDiagnosticLog:
    fixed = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)
    return LoadControlDiagnosticLog(max_events=100, utc_now=lambda: fixed)


def _sample(real_sample, *, cycle_id: int, started_ns: int, quality=SampleQuality.VALID):
    duration_ns = max(1, real_sample.timing.cycle_finished_monotonic_ns - real_sample.timing.cycle_started_monotonic_ns)
    return replace(
        real_sample,
        identity=replace(real_sample.identity, cycle_id=cycle_id),
        timing=replace(
            real_sample.timing,
            cycle_started_monotonic_ns=started_ns,
            cycle_finished_monotonic_ns=started_ns + duration_ns,
        ),
        quality=quality,
    )


def _ack(command, **changes) -> AckFrame:
    values = {
        "protocol_version": 1,
        "viewer_session_id": command.viewer_session_id,
        "node_id": command.node_id,
        "boot_id": command.boot_id,
        "sequence": command.sequence,
        "ack_utc": "2026-09-01T19:00:00.500000+00:00",
        "applied_p": ZERO,
        "result": "APPLIED",
    }
    values.update(changes)
    return AckFrame(**values)


def _status(command) -> StatusFrame:
    return StatusFrame(
        protocol_version=1,
        node_id=command.node_id,
        boot_id=command.boot_id,
        status_utc="2026-09-01T19:00:00.400000+00:00",
        applied_p=ZERO,
        state="READY",
        faults=(),
    )


def _service(
    bus: RuntimeEventBus,
    channel: FakeQualifiedChannel,
    *,
    config: RuntimeConfig | None = None,
    clock: FakeClock | None = None,
    diagnostic_log: LoadControlDiagnosticLog | None = None,
    wait_for=asyncio.wait_for,
) -> Stage3ASafeCommandService:
    clock = clock or FakeClock()
    return Stage3ASafeCommandService(
        bus,
        config or _config(),
        channel,
        diagnostic_log=diagnostic_log or _diagnostic_log(),
        viewer_session_id="VIEWER-STAGE3A-001",
        utc_now=clock.utc_now,
        monotonic_ns=clock.monotonic_ns,
        wait_for=wait_for,
    )


async def _settle() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


def test_stage3a_starts_idle_and_lists_only_enabled_sources() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel)
        await service.start()

        assert service.status().state is Stage3AState.IDLE
        assert service.status().selected_source_id is None
        assert service.status().admissible is False
        assert tuple((item.id, item.name, item.poll_interval_s) for item in service.sources()) == (
            ("emonio-example", "Emonio Example", 0.05),
        )

        disabled = _service(bus, channel, config=_config(enabled=False))
        await disabled.start()
        assert disabled.sources() == ()

        await disabled.close()
        await service.close()

    asyncio.run(scenario())


def test_stage3a_source_selection_is_explicit_volatile_and_validated() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        diagnostic = _diagnostic_log()
        service = _service(bus, channel, diagnostic_log=diagnostic)
        await service.start()

        status = await service.select_source("emonio-example")
        assert status.state is Stage3AState.READY
        assert status.selected_source_id == "emonio-example"
        assert status.admissible is True
        assert diagnostic.recent()[-1].event == "SAFE_SOURCE_SELECTED"

        with pytest.raises(Stage3AError, match="SOURCE_NOT_AVAILABLE"):
            await service.select_source("missing")

        await service.close()
        assert service.status().selected_source_id is None

    asyncio.run(scenario())


def test_stage3a_requires_explicit_source_and_qualified_actuator() -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel)
        await service.start()

        with pytest.raises(Stage3AError, match="SOURCE_NOT_SELECTED"):
            await service.run_safe_test()
        assert service.status().state is Stage3AState.REJECTED
        assert service.status().rejection_reason == "SOURCE_NOT_SELECTED"
        assert channel.sent == []

        await service.select_source("emonio-example")
        channel.current_hello = None
        with pytest.raises(Stage3AError, match="ACTUATOR_NOT_QUALIFIED"):
            await service.run_safe_test()
        assert service.status().rejection_reason == "ACTUATOR_NOT_QUALIFIED"
        assert channel.sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage3a_waits_for_first_valid_post_request_sample(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        bus.publish(_sample(real_sample, cycle_id=40, started_ns=9_000_000_000))
        await _settle()

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        assert service.status().state is Stage3AState.WAITING_FOR_SAMPLE

        bus.publish(_sample(real_sample, cycle_id=41, started_ns=9_500_000_000))
        bus.publish(_sample(real_sample, cycle_id=42, started_ns=10_100_000_000, quality=SampleQuality.INVALID))
        await _settle()
        assert channel.sent == []

        bus.publish(_sample(real_sample, cycle_id=43, started_ns=10_200_000_000))
        await _settle()
        assert len(channel.sent) == 1
        command = channel.sent[0]
        channel.push(_ack(command))
        status = await request

        assert status.state is Stage3AState.PASSED
        assert status.sample_cycle_id == 43
        assert command.measurement_cycle_id == 43

        await service.close()

    asyncio.run(scenario())


def test_stage3a_sample_timeout_is_twice_poll_interval_and_sends_nothing() -> None:
    async def scenario() -> None:
        observed = []

        async def fake_wait_for(awaitable, timeout):
            observed.append(timeout)
            if hasattr(awaitable, "cancel"):
                awaitable.cancel()
            raise asyncio.TimeoutError()

        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel, config=_config(poll_interval_s=0.125), wait_for=fake_wait_for)
        await service.start()
        await service.select_source("emonio-example")

        status = await service.run_safe_test()
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "NO_NEW_VALID_SAMPLE"
        assert observed[0] == pytest.approx(0.25)
        assert channel.sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage3a_acquisition_failure_after_request_rejects_without_command(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")
        bus.publish(_sample(real_sample, cycle_id=7, started_ns=9_000_000_000))
        await _settle()

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(
            DiagnosticEvent(
                device_id="emonio-example",
                cycle_id=8,
                occurred_utc=datetime(2026, 9, 1, 19, 0, 1, tzinfo=timezone.utc),
                event="ACQUISITION_TIMEOUT",
                severity=Severity.WARNING,
                detail="A: timed out",
            )
        )
        status = await request

        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "SOURCE_ACQUISITION_FAILURE"
        assert channel.sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage3a_builds_exact_zero_command_from_canonical_sample(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        diagnostic = _diagnostic_log()
        service = _service(bus, channel, clock=clock, diagnostic_log=diagnostic)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        accepted = _sample(real_sample, cycle_id=12, started_ns=10_100_000_000)
        bus.publish(accepted)
        await _settle()
        assert len(channel.sent) == 1
        command = channel.sent[0]

        assert command.protocol_version == 1
        assert command.viewer_session_id == "VIEWER-STAGE3A-001"
        assert command.node_id == "ARI-LOAD-001"
        assert command.boot_id == "BOOT-STAGE3A-001"
        assert command.sequence == 1
        assert command.emonio_device_id == "emonio-example"
        assert command.measurement_cycle_id == 12
        assert command.measurement_utc == accepted.timing.cycle_finished_utc.isoformat()
        assert command.command_utc == clock.utc_value.isoformat()
        assert command.control_enabled is False
        assert command.p_reserve == 0.0
        assert command.measured_p == ThreePhasePower(
            accepted.phase_a.measurement.p,
            accepted.phase_b.measurement.p,
            accepted.phase_c.measurement.p,
        )
        assert command.measured_q == ThreePhasePower(
            accepted.phase_a.measurement.q,
            accepted.phase_b.measurement.q,
            accepted.phase_c.measurement.q,
        )
        assert command.p_load_request == ZERO
        assert command.q_comp_request == ZERO

        channel.push(_ack(command))
        status = await request
        assert status.state is Stage3AState.PASSED

        assert tuple(item.event for item in diagnostic.recent() if item.event.startswith("SAFE_")) == (
            "SAFE_SOURCE_SELECTED",
            "SAFE_TEST_REQUESTED",
            "SAFE_SAMPLE_WAIT_STARTED",
            "SAFE_SAMPLE_ACCEPTED",
            "SAFE_COMMAND_SENT",
            "SAFE_ACK_RECEIVED",
            "SAFE_ACK_QUALIFIED",
            "SAFE_TEST_PASSED",
        )

        await service.close()

    asyncio.run(scenario())


def test_stage3a_status_before_ack_does_not_extend_original_two_second_deadline(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        channel.advance_on_receive_s = 0.5
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=2, started_ns=10_100_000_000))
        await _settle()
        command = channel.sent[0]
        channel.push(_status(command))
        channel.push(_ack(command))

        status = await request
        assert status.state is Stage3AState.PASSED
        assert channel.receive_timeouts[0] == pytest.approx(2.0)
        assert channel.receive_timeouts[1] == pytest.approx(1.5)

        await service.close()

    asyncio.run(scenario())


def test_stage3a_ack_timeout_rejects_without_retry(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=3, started_ns=10_100_000_000))
        await _settle()
        assert len(channel.sent) == 1

        status = await request
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "ACK_TIMEOUT"
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"viewer_session_id": "VIEWER-OTHER"}, "ACK_SESSION_MISMATCH"),
        ({"node_id": "ARI-LOAD-OTHER"}, "ACK_NODE_MISMATCH"),
        ({"boot_id": "BOOT-OTHER"}, "ACK_BOOT_MISMATCH"),
        ({"sequence": 999}, "ACK_SEQUENCE_MISMATCH"),
        ({"result": "REJECTED"}, "ACK_RESULT_MISMATCH"),
        ({"applied_p": ThreePhasePower(0.1, 0.0, 0.0)}, "ACK_APPLIED_P_MISMATCH"),
    ],
)
def test_stage3a_rejects_each_ack_mismatch_without_retry(real_sample, changes, reason) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=4, started_ns=10_100_000_000))
        await _settle()
        command = channel.sent[0]
        channel.push(_ack(command, **changes))

        status = await request
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == reason
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())


def test_stage3a_maps_unsupported_ack_protocol_to_protocol_mismatch(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=5, started_ns=10_100_000_000))
        await _settle()
        channel.push(ProtocolError("unsupported protocol_version"))

        status = await request
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "ACK_PROTOCOL_MISMATCH"
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())


def test_stage3a_disconnect_during_ack_wait_rejects_without_retry(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=6, started_ns=10_100_000_000))
        await _settle()
        channel.current_hello = None
        channel.push(ConnectionError("actuator WebSocket disconnected"))

        status = await request
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "ACTUATOR_DISCONNECTED"
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())


def test_stage3a_failed_send_consumes_sequence_and_never_retries(real_sample) -> None:
    async def run_one(service, bus, channel, sample):
        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(sample)
        return await request

    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        channel.send_error = OSError("send failed")
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        first = await run_one(service, bus, channel, _sample(real_sample, cycle_id=10, started_ns=10_100_000_000))
        assert first.state is Stage3AState.REJECTED
        assert first.rejection_reason == "COMMAND_SEND_FAILED"
        assert [item.sequence for item in channel.sent] == [1]

        clock.advance(1.0)
        second = await run_one(service, bus, channel, _sample(real_sample, cycle_id=11, started_ns=11_100_000_000))
        assert second.state is Stage3AState.REJECTED
        assert second.rejection_reason == "COMMAND_SEND_FAILED"
        assert [item.sequence for item in channel.sent] == [1, 2]

        await service.close()

    asyncio.run(scenario())


def test_stage3a_rejects_source_change_and_second_test_while_exchange_active(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock(monotonic_ns=10_000_000_000)
        channel = FakeQualifiedChannel(_hello(), clock=clock)
        service = _service(bus, channel, clock=clock)
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _settle()
        assert service.status().state is Stage3AState.WAITING_FOR_SAMPLE

        with pytest.raises(Stage3AError, match="SAFE_TEST_ACTIVE"):
            await service.select_source("emonio-example")
        with pytest.raises(Stage3AError, match="SAFE_TEST_ACTIVE"):
            await service.run_safe_test()
        assert channel.sent == []

        bus.publish(_sample(real_sample, cycle_id=20, started_ns=10_100_000_000))
        await _settle()
        command = channel.sent[0]
        channel.push(_ack(command))
        assert (await request).state is Stage3AState.PASSED
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())
