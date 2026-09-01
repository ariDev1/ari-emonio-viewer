import asyncio

from emonio_viewer.load_control.discovery import MockActuatorDiscovery
from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.protocol import CommandFrame
from emonio_viewer.load_control.session import MockAckMode, MockActuatorSession


def descriptor(node_id="ARI-LOAD-MOCK-001", location="mock://load-001"):
    return ActuatorDescriptor(
        node_id=node_id,
        location=location,
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(600.0, 700.0, 800.0),
    )


def command(sequence=1, node_id="ARI-LOAD-MOCK-001", boot_id="MOCK-BOOT-001", p=None):
    return CommandFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-TEST-001",
        node_id=node_id,
        boot_id=boot_id,
        sequence=sequence,
        emonio_device_id="emonio-example",
        measurement_cycle_id=10,
        measurement_utc="2026-09-01T11:00:00+00:00",
        command_utc="2026-09-01T11:00:00.050000+00:00",
        control_enabled=bool(p and (p.a or p.b or p.c)),
        p_reserve=30.0,
        measured_p=ThreePhasePower(-420.0, 0.0, 0.0),
        measured_q=ThreePhasePower(0.0, 0.0, 0.0),
        p_load_request=p or ThreePhasePower(0.0, 0.0, 0.0),
        q_comp_request=ThreePhasePower(0.0, 0.0, 0.0),
    )


def test_mock_discovery_never_selects_or_rebinds():
    async def scenario():
        a = descriptor()
        b = descriptor("ARI-LOAD-MOCK-002", "mock://load-002")
        discovery = MockActuatorDiscovery((a, b))
        assert await discovery.discover() == (a, b)
        discovery.set_visible((b,))
        assert await discovery.discover() == (b,)
        assert not hasattr(discovery, "selected_node_id")
    asyncio.run(scenario())


def test_mock_session_exact_ack_reports_applied_request():
    async def scenario():
        session = MockActuatorSession(descriptor(), boot_id="MOCK-BOOT-001")
        hello = await session.connect()
        assert hello.node_id == "ARI-LOAD-MOCK-001"
        sent = command(sequence=5, p=ThreePhasePower(100.0, 200.0, 300.0))
        await session.send_command(sent)
        ack = await session.receive_ack()
        assert ack is not None
        assert ack.sequence == 5
        assert ack.applied_p == ThreePhasePower(100.0, 200.0, 300.0)
        assert session.sent_commands == (sent,)
    asyncio.run(scenario())


def test_mock_session_can_withhold_ack_without_random_behavior():
    async def scenario():
        session = MockActuatorSession(
            descriptor(),
            boot_id="MOCK-BOOT-001",
            ack_mode=MockAckMode.NONE,
        )
        await session.connect()
        await session.send_command(command(sequence=6))
        assert await session.receive_ack() is None
    asyncio.run(scenario())


def test_mock_session_can_emit_wrong_sequence_for_fault_testing():
    async def scenario():
        session = MockActuatorSession(
            descriptor(),
            boot_id="MOCK-BOOT-001",
            ack_mode=MockAckMode.WRONG_SEQUENCE,
        )
        await session.connect()
        await session.send_command(command(sequence=7))
        ack = await session.receive_ack()
        assert ack is not None
        assert ack.sequence == 8
    asyncio.run(scenario())


def test_mock_reboot_changes_boot_identity_and_clears_applied_state():
    async def scenario():
        session = MockActuatorSession(descriptor(), boot_id="MOCK-BOOT-001")
        await session.connect()
        await session.send_command(command(sequence=8, p=ThreePhasePower(50.0, 60.0, 70.0)))
        assert (await session.receive_ack()).applied_p == ThreePhasePower(50.0, 60.0, 70.0)
        session.reboot("MOCK-BOOT-002")
        assert session.boot_id == "MOCK-BOOT-002"
        assert session.applied_p == ThreePhasePower(0.0, 0.0, 0.0)
        assert session.connected is False
    asyncio.run(scenario())
