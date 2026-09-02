import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import AckFrame, HelloFrame
from emonio_viewer.load_control.stage3a import Stage3AError, Stage3ASafeCommandService, Stage3AState
from emonio_viewer.measurement.model import SampleQuality
from emonio_viewer.runtime.events import RuntimeEventBus


ZERO = ThreePhasePower(0.0, 0.0, 0.0)
ONE_A = ThreePhasePower(1.0, 0.0, 0.0)


class FakeClock:
    def __init__(self, *, monotonic_ns: int = 10_000_000_000) -> None:
        self.monotonic_ns_value = monotonic_ns
        self.utc_value = datetime(2026, 9, 2, 6, 0, 0, tzinfo=timezone.utc)

    def monotonic_ns(self) -> int:
        return self.monotonic_ns_value

    def utc_now(self) -> datetime:
        return self.utc_value


class FakeQualifiedChannel:
    def __init__(self, hello: HelloFrame | None = None) -> None:
        self.current_hello = hello
        self.sent = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self.send_error: Exception | None = None

    def hello(self) -> HelloFrame | None:
        return self.current_hello

    async def send(self, command) -> None:
        self.sent.append(command)
        if self.send_error is not None:
            raise self.send_error

    async def receive(self, timeout_s: float):
        item = await asyncio.wait_for(self.frames.get(), timeout_s)
        if isinstance(item, Exception):
            raise item
        return item

    def push(self, item: object) -> None:
        self.frames.put_nowait(item)


def _hello(*, p_max_a: float = 1000.0, boot_id: str = "BOOT-STAGE3B-001") -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id=boot_id,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(p_max_a, 1000.0, 1000.0),
    )


def _config() -> RuntimeConfig:
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
                poll_interval_s=0.05,
                timeout_s=0.1,
                enabled=True,
                firmware_version="3.0.79-release",
            ),
        ),
    )


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


def _ack(command, applied_p: ThreePhasePower) -> AckFrame:
    return AckFrame(
        protocol_version=1,
        viewer_session_id=command.viewer_session_id,
        node_id=command.node_id,
        boot_id=command.boot_id,
        sequence=command.sequence,
        ack_utc="2026-09-02T06:00:00.500000+00:00",
        applied_p=applied_p,
        result="APPLIED",
    )


def _service(bus: RuntimeEventBus, channel: FakeQualifiedChannel) -> Stage3ASafeCommandService:
    clock = FakeClock()
    return Stage3ASafeCommandService(
        bus,
        _config(),
        channel,
        viewer_session_id="VIEWER-STAGE3B-001",
        utc_now=clock.utc_now,
        monotonic_ns=clock.monotonic_ns,
    )


async def _settle() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


async def _wait_for_command(channel: FakeQualifiedChannel, *, count: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.5
    while len(channel.sent) < count:
        if loop.time() >= deadline:
            raise AssertionError(f"expected {count} command(s), observed {len(channel.sent)}")
        await asyncio.sleep(0.001)


def test_stage3b_fixed_1w_phase_a_requires_explicit_zero_reset(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel)
        await service.start()
        await service.select_source("emonio-example")

        run_simulated = getattr(service, "run_simulated_test", None)
        simulated_status = getattr(service, "simulated_status", None)
        assert callable(run_simulated), "Stage 3B must add one explicit simulated nonzero test action"
        assert callable(simulated_status), "Stage 3B must expose its reset latch status"

        request = asyncio.create_task(run_simulated())
        await _settle()
        accepted = _sample(real_sample, cycle_id=20, started_ns=10_100_000_000)
        bus.publish(accepted)
        await _wait_for_command(channel, count=1)
        command = channel.sent[0]

        assert command.sequence == 1
        assert command.control_enabled is True
        assert command.p_reserve == 1.0
        assert command.p_load_request == ONE_A
        assert command.q_comp_request == ZERO
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

        channel.push(_ack(command, ONE_A))
        result = await request
        assert result.state.value == "RESET_REQUIRED"
        stage3b = simulated_status()
        assert stage3b.safe_reset_required is True
        assert stage3b.admissible is False
        assert stage3b.fixed_request == ONE_A

        with pytest.raises(Stage3AError, match="SAFE_RESET_REQUIRED"):
            await run_simulated()
        assert len(channel.sent) == 1

        reset = asyncio.create_task(service.run_safe_test())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=21, started_ns=10_200_000_000))
        await _wait_for_command(channel, count=2)
        zero_command = channel.sent[1]
        assert zero_command.sequence == 2
        assert zero_command.control_enabled is False
        assert zero_command.p_load_request == ZERO

        channel.push(_ack(zero_command, ZERO))
        reset_result = await reset
        assert reset_result.state is Stage3AState.PASSED
        assert simulated_status().safe_reset_required is False
        assert simulated_status().admissible is True

        await service.close()

    asyncio.run(scenario())


def test_stage3b_rejects_below_fixed_1w_advertised_limit_without_send(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello(p_max_a=0.5))
        service = _service(bus, channel)
        await service.start()
        await service.select_source("emonio-example")

        run_simulated = getattr(service, "run_simulated_test", None)
        simulated_status = getattr(service, "simulated_status", None)
        assert callable(run_simulated)
        assert callable(simulated_status)

        request = asyncio.create_task(run_simulated())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=30, started_ns=10_100_000_000))
        result = await request

        assert result.state is Stage3AState.REJECTED
        assert result.rejection_reason == "SIMULATED_TEST_LIMIT_INSUFFICIENT"
        assert channel.sent == []
        assert simulated_status().safe_reset_required is False

        await service.close()

    asyncio.run(scenario())


def test_stage3b_send_failure_latches_reset_requirement(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        channel.send_error = RuntimeError("synthetic send failure")
        service = _service(bus, channel)
        await service.start()
        await service.select_source("emonio-example")

        run_simulated = getattr(service, "run_simulated_test", None)
        simulated_status = getattr(service, "simulated_status", None)
        assert callable(run_simulated)
        assert callable(simulated_status)

        request = asyncio.create_task(run_simulated())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=40, started_ns=10_100_000_000))
        result = await request

        assert result.state is Stage3AState.REJECTED
        assert result.rejection_reason == "COMMAND_SEND_FAILED"
        assert simulated_status().safe_reset_required is True

        with pytest.raises(Stage3AError, match="SAFE_RESET_REQUIRED"):
            await run_simulated()
        assert len(channel.sent) == 1

        await service.close()

    asyncio.run(scenario())


def test_stage3b_requires_exact_nonzero_ack(real_sample) -> None:
    async def scenario() -> None:
        bus = RuntimeEventBus()
        channel = FakeQualifiedChannel(_hello())
        service = _service(bus, channel)
        await service.start()
        await service.select_source("emonio-example")

        run_simulated = getattr(service, "run_simulated_test", None)
        simulated_status = getattr(service, "simulated_status", None)
        assert callable(run_simulated)
        assert callable(simulated_status)

        request = asyncio.create_task(run_simulated())
        await _settle()
        bus.publish(_sample(real_sample, cycle_id=50, started_ns=10_100_000_000))
        await _wait_for_command(channel, count=1)
        command = channel.sent[0]
        channel.push(_ack(command, ThreePhasePower(0.999, 0.0, 0.0)))
        result = await request

        assert result.state is Stage3AState.REJECTED
        assert result.rejection_reason == "ACK_APPLIED_P_MISMATCH"
        assert simulated_status().safe_reset_required is True

        await service.close()

    asyncio.run(scenario())
