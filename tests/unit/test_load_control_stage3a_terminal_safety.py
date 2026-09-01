import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.diagnostic_log import LoadControlDiagnosticLog
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import AckFrame, HelloFrame
from emonio_viewer.load_control.qualified_channel import QualifiedActuatorChannel
from emonio_viewer.load_control.stage3a import Stage3ASafeCommandService, Stage3AState
from emonio_viewer.measurement.model import SampleQuality
from emonio_viewer.runtime.events import RuntimeEventBus


ZERO = ThreePhasePower(0.0, 0.0, 0.0)


class FakeClock:
    def __init__(self) -> None:
        self.value = 10_000_000_000
        self.utc = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)

    def monotonic_ns(self) -> int:
        return self.value

    def utc_now(self) -> datetime:
        return self.utc

    def advance(self, seconds: float) -> None:
        self.value += int(seconds * 1_000_000_000)


class FakeQualifiedChannel:
    def __init__(self, hello: HelloFrame) -> None:
        self.current_hello = hello
        self.sent = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self._disconnect_event = asyncio.Event()
        self.timeout_next_receive = False

    def hello(self):
        return self.current_hello

    def disconnect_event(self):
        return self._disconnect_event

    def disconnect(self) -> None:
        self.current_hello = None
        self._disconnect_event.set()

    async def send(self, command) -> None:
        self.sent.append(command)

    async def receive(self, timeout_s: float):
        if self.timeout_next_receive:
            self.timeout_next_receive = False
            raise asyncio.TimeoutError()
        item = await asyncio.wait_for(self.frames.get(), timeout_s)
        if isinstance(item, Exception):
            raise item
        return item

    def receive_nowait(self):
        item = self.frames.get_nowait()
        if isinstance(item, Exception):
            raise item
        return item

    def push(self, item: object) -> None:
        self.frames.put_nowait(item)


class FakeBoundSession:
    connected = True

    def __init__(self, item) -> None:
        self.item = item

    def receive_frame_nowait(self):
        return self.item


def _hello() -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id="BOOT-STAGE3A-SAFETY",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _config(*, poll_interval_s: float = 0.05) -> RuntimeConfig:
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
                enabled=True,
                firmware_version="3.0.79-release",
            ),
        ),
    )


def _log() -> LoadControlDiagnosticLog:
    fixed = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)
    return LoadControlDiagnosticLog(max_events=100, utc_now=lambda: fixed)


def _sample(real_sample, *, cycle_id: int, started_ns: int):
    duration_ns = max(
        1,
        real_sample.timing.cycle_finished_monotonic_ns
        - real_sample.timing.cycle_started_monotonic_ns,
    )
    return replace(
        real_sample,
        identity=replace(real_sample.identity, cycle_id=cycle_id),
        timing=replace(
            real_sample.timing,
            cycle_started_monotonic_ns=started_ns,
            cycle_finished_monotonic_ns=started_ns + duration_ns,
        ),
        quality=SampleQuality.VALID,
    )


def _ack(command) -> AckFrame:
    return AckFrame(
        protocol_version=1,
        viewer_session_id=command.viewer_session_id,
        node_id=command.node_id,
        boot_id=command.boot_id,
        sequence=command.sequence,
        ack_utc="2026-09-01T19:00:00.500000+00:00",
        applied_p=ZERO,
        result="APPLIED",
    )


async def _wait_for_state(service, state: Stage3AState, timeout_s: float = 0.5) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while service.status().state is not state:
        if loop.time() >= deadline:
            raise AssertionError(f"expected state {state.value}, got {service.status().state.value}")
        await asyncio.sleep(0.001)


async def _wait_for_commands(channel: FakeQualifiedChannel, count: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while len(channel.sent) < count:
        if loop.time() >= deadline:
            raise AssertionError(f"expected {count} command(s), got {len(channel.sent)}")
        await asyncio.sleep(0.001)


def test_qualified_channel_exposes_disconnect_boundary_and_nonblocking_receive() -> None:
    channel = QualifiedActuatorChannel()
    marker = object()
    session = FakeBoundSession(marker)
    channel.bind(session, _hello())

    disconnect_event = channel.disconnect_event()
    assert disconnect_event.is_set() is False
    assert channel.receive_nowait() is marker

    channel.clear(session)
    assert disconnect_event.is_set() is True


def test_stage3a_disconnect_during_sample_wait_rejects_immediately_without_command(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock()
        channel = FakeQualifiedChannel(_hello())
        service = Stage3ASafeCommandService(
            bus,
            _config(poll_interval_s=1.0),
            channel,
            diagnostic_log=_log(),
            viewer_session_id="VIEWER-STAGE3A-SAFETY",
            utc_now=clock.utc_now,
            monotonic_ns=clock.monotonic_ns,
        )
        await service.start()
        await service.select_source("emonio-example")

        request = asyncio.create_task(service.run_safe_test())
        await _wait_for_state(service, Stage3AState.WAITING_FOR_SAMPLE)
        channel.disconnect()

        status = await asyncio.wait_for(request, 0.25)
        assert status.state is Stage3AState.REJECTED
        assert status.rejection_reason == "ACTUATOR_DISCONNECTED"
        assert channel.sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage3a_late_ack_is_logged_unexpected_and_cannot_poison_next_test(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        clock = FakeClock()
        channel = FakeQualifiedChannel(_hello())
        diagnostic = _log()
        service = Stage3ASafeCommandService(
            bus,
            _config(),
            channel,
            diagnostic_log=diagnostic,
            viewer_session_id="VIEWER-STAGE3A-SAFETY",
            utc_now=clock.utc_now,
            monotonic_ns=clock.monotonic_ns,
        )
        await service.start()
        await service.select_source("emonio-example")

        channel.timeout_next_receive = True
        first = asyncio.create_task(service.run_safe_test())
        await _wait_for_state(service, Stage3AState.WAITING_FOR_SAMPLE)
        bus.publish(_sample(real_sample, cycle_id=1, started_ns=10_100_000_000))
        await _wait_for_commands(channel, 1)
        first_status = await first
        assert first_status.state is Stage3AState.REJECTED
        assert first_status.rejection_reason == "ACK_TIMEOUT"

        channel.push(_ack(channel.sent[0]))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 0.3
        while not any(item.event == "SAFE_ACK_UNEXPECTED" for item in diagnostic.recent()):
            if loop.time() >= deadline:
                raise AssertionError("late ACK was not logged as SAFE_ACK_UNEXPECTED")
            await asyncio.sleep(0.01)

        clock.advance(1.0)
        second = asyncio.create_task(service.run_safe_test())
        await _wait_for_state(service, Stage3AState.WAITING_FOR_SAMPLE)
        bus.publish(_sample(real_sample, cycle_id=2, started_ns=11_100_000_000))
        await _wait_for_commands(channel, 2)
        channel.push(_ack(channel.sent[1]))
        second_status = await second

        assert second_status.state is Stage3AState.PASSED
        assert second_status.command_sequence == 2
        assert [command.sequence for command in channel.sent] == [1, 2]

        await service.close()

    asyncio.run(scenario())
