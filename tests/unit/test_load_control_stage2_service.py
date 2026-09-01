import asyncio

import pytest

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.protocol import HelloFrame, ProtocolError
from emonio_viewer.load_control.qualification import (
    LoadControlQualificationError,
    LoadControlQualificationService,
    QualificationState,
)


class FakeLanDiscoveryService:
    def __init__(self, *items: ActuatorDescriptor) -> None:
        self.last_result = tuple(items)


class FakeSession:
    def __init__(
        self,
        descriptor: ActuatorDescriptor,
        *,
        hello: HelloFrame | None,
        receive_error: Exception | None,
        observe_state=None,
        open_gate: asyncio.Event | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.hello = hello
        self.receive_error = receive_error
        self.observe_state = observe_state
        self.open_gate = open_gate
        self.connected = False
        self.sent = []
        self.disconnect_calls = 0
        self.disconnect_event = asyncio.Event()

    async def open(self) -> None:
        if self.observe_state is not None:
            self.observe_state("open")
        if self.open_gate is not None:
            await self.open_gate.wait()
        self.connected = True

    async def receive_hello(self) -> HelloFrame:
        if self.observe_state is not None:
            self.observe_state("receive_hello")
        if self.receive_error is not None:
            raise self.receive_error
        assert self.hello is not None
        return self.hello

    async def wait_for_disconnect(self) -> None:
        await self.disconnect_event.wait()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def trigger_remote_disconnect(self) -> None:
        self.connected = False
        self.disconnect_event.set()


class FakeSessionFactory:
    def __init__(self, *specs) -> None:
        self.specs = list(specs)
        self.created = []
        self.state_getter = None
        self.observed = []

    def __call__(self, descriptor, *, connect_timeout_s, receive_timeout_s):
        if self.state_getter is not None:
            self.observed.append(("factory", self.state_getter().state))
        spec = self.specs.pop(0)

        def observe(label):
            if self.state_getter is not None:
                self.observed.append((label, self.state_getter().state))

        session = FakeSession(
            descriptor,
            hello=spec.get("hello"),
            receive_error=spec.get("receive_error"),
            observe_state=observe,
            open_gate=spec.get("open_gate"),
        )
        session.connect_timeout_s = connect_timeout_s
        session.receive_timeout_s = receive_timeout_s
        self.created.append(session)
        return session


def _descriptor(node_id: str = "ARI-LOAD-001") -> ActuatorDescriptor:
    return ActuatorDescriptor(
        node_id=node_id,
        location="ws://192.168.1.141:8080/load-control",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _hello(boot_id: str = "BOOT-001") -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id=boot_id,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _service(discovery, factory):
    service = LoadControlQualificationService(
        discovery,
        session_factory=factory,
    )
    factory.state_getter = service.status
    return service


def test_stage2_service_is_idle_and_does_not_auto_select_discovery() -> None:
    factory = FakeSessionFactory({"hello": _hello()})
    service = _service(FakeLanDiscoveryService(_descriptor()), factory)

    status = service.status()
    assert status.state is QualificationState.IDLE
    assert status.selected_node_id is None
    assert status.node_id is None
    assert status.connected is False
    assert factory.created == []


def test_stage2_service_rejects_missing_or_ambiguous_operator_selection() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        with pytest.raises(LoadControlQualificationError, match="latest LAN discovery"):
            await service.connect("ARI-LOAD-MISSING")

        duplicate = _service(
            FakeLanDiscoveryService(_descriptor(), _descriptor()),
            FakeSessionFactory({"hello": _hello()}),
        )
        with pytest.raises(LoadControlQualificationError, match="ambiguous"):
            await duplicate.connect("ARI-LOAD-001")

        assert factory.created == []
        await service.close()
        await duplicate.close()

    asyncio.run(scenario())


def test_stage2_service_uses_required_state_order_and_timeouts() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        status = await service.connect("ARI-LOAD-001")

        assert factory.observed == [
            ("factory", QualificationState.DISCOVERED),
            ("open", QualificationState.CONNECTING),
            ("receive_hello", QualificationState.HELLO_WAIT),
        ]
        assert status.state is QualificationState.QUALIFIED
        assert status.connected is True
        assert status.hello_qualified is True
        assert status.node_id == "ARI-LOAD-001"
        assert status.boot_id == "BOOT-001"
        assert factory.created[0].connect_timeout_s == 3.0
        assert factory.created[0].receive_timeout_s == 2.0
        assert factory.created[0].sent == []

        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error",
    [
        ProtocolError("invalid HELLO"),
        asyncio.TimeoutError(),
    ],
)
def test_stage2_service_rejects_transport_or_hello_failure_without_sending(error) -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"receive_error": error})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        status = await service.connect("ARI-LOAD-001")

        assert status.state is QualificationState.REJECTED
        assert status.connected is False
        assert status.hello_qualified is False
        assert status.node_id is None
        assert status.boot_id is None
        assert factory.created[0].sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage2_service_requires_disconnect_before_second_connection() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()}, {"hello": _hello("BOOT-002")})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        await service.connect("ARI-LOAD-001")
        with pytest.raises(LoadControlQualificationError, match="already open"):
            await service.connect("ARI-LOAD-001")

        assert len(factory.created) == 1
        await service.close()

    asyncio.run(scenario())


def test_stage2_service_rejects_second_connect_while_first_is_connecting() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        factory = FakeSessionFactory(
            {"hello": _hello(), "open_gate": gate},
            {"hello": _hello("BOOT-002")},
        )
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        first_task = asyncio.create_task(service.connect("ARI-LOAD-001"))
        await asyncio.sleep(0)
        assert service.status().state is QualificationState.CONNECTING

        with pytest.raises(LoadControlQualificationError, match="already open"):
            await service.connect("ARI-LOAD-001")
        assert len(factory.created) == 1

        gate.set()
        first = await first_task
        assert first.state is QualificationState.QUALIFIED
        assert first.boot_id == "BOOT-001"
        assert factory.created[0].sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage2_disconnect_requested_during_connect_runs_after_connect_operation() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        factory = FakeSessionFactory({"hello": _hello(), "open_gate": gate})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        connect_task = asyncio.create_task(service.connect("ARI-LOAD-001"))
        await asyncio.sleep(0)
        assert service.status().state is QualificationState.CONNECTING

        disconnect_task = asyncio.create_task(service.disconnect())
        await asyncio.sleep(0)
        assert disconnect_task.done() is False

        gate.set()
        connected = await connect_task
        assert connected.state is QualificationState.QUALIFIED

        disconnected = await disconnect_task
        assert disconnected.state is QualificationState.DISCONNECTED
        assert disconnected.connected is False
        assert disconnected.hello_qualified is False
        assert disconnected.node_id is None
        assert disconnected.boot_id is None
        assert factory.created[0].sent == []

    asyncio.run(scenario())


def test_stage2_explicit_disconnect_clears_qualified_identity_and_sends_no_frame() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        await service.connect("ARI-LOAD-001")
        status = await service.disconnect()

        assert status.state is QualificationState.DISCONNECTED
        assert status.connected is False
        assert status.hello_qualified is False
        assert status.selected_node_id == "ARI-LOAD-001"
        assert status.node_id is None
        assert status.boot_id is None
        assert factory.created[0].sent == []

    asyncio.run(scenario())


def test_stage2_reconnect_requires_new_hello_and_accepts_new_boot_instance() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello("BOOT-001")}, {"hello": _hello("BOOT-002")})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        first = await service.connect("ARI-LOAD-001")
        assert first.boot_id == "BOOT-001"
        await service.disconnect()

        second = await service.connect("ARI-LOAD-001")
        assert second.state is QualificationState.QUALIFIED
        assert second.boot_id == "BOOT-002"
        assert len(factory.created) == 2
        assert all(session.sent == [] for session in factory.created)

        await service.close()

    asyncio.run(scenario())


def test_stage2_remote_disconnect_invalidates_qualification() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        qualified = await service.connect("ARI-LOAD-001")
        assert qualified.state is QualificationState.QUALIFIED

        factory.created[0].trigger_remote_disconnect()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        status = service.status()
        assert status.state is QualificationState.DISCONNECTED
        assert status.connected is False
        assert status.hello_qualified is False
        assert status.node_id is None
        assert status.boot_id is None
        assert factory.created[0].sent == []

        await service.close()

    asyncio.run(scenario())


def test_stage2_close_sends_no_frame() -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory({"hello": _hello()})
        service = _service(FakeLanDiscoveryService(_descriptor()), factory)

        await service.connect("ARI-LOAD-001")
        await service.close()

        assert factory.created[0].sent == []
        assert service.status().state is QualificationState.DISCONNECTED

    asyncio.run(scenario())
