import asyncio

from emonio_viewer.load_control.discovery import MdnsResolvedService
from emonio_viewer.load_control.lan_discovery import LanActuatorDiscoveryService


class FakeBackend:
    def __init__(self) -> None:
        self.calls = []

    async def scan(
        self,
        *,
        service_type: str,
        discovery_window_s: float,
        resolve_timeout_s: float,
    ):
        self.calls.append((service_type, discovery_window_s, resolve_timeout_s))
        return (
            MdnsResolvedService(
                address="192.168.20.44",
                port=8765,
                properties={
                    b"node_id": b"ARI-LOAD-001",
                    b"device_class": b"ARI_LOAD_ACTUATOR",
                    b"capabilities": b"ACTIVE_LOAD_CONTROL",
                    b"p_max_a_w": b"1200.0",
                    b"p_max_b_w": b"1200.0",
                    b"p_max_c_w": b"1200.0",
                    b"ws_path": b"/control",
                },
            ),
        )


def test_lan_discovery_service_scans_only_when_explicitly_requested() -> None:
    async def scenario() -> None:
        backend = FakeBackend()
        service = LanActuatorDiscoveryService(backend=backend)

        assert service.last_result == ()
        visible = await service.scan(
            discovery_window_s=0.25,
            resolve_timeout_s=0.15,
        )

        assert backend.calls == [
            ("_ari-emonio-load._tcp.local.", 0.25, 0.15)
        ]
        assert tuple(item.node_id for item in visible) == ("ARI-LOAD-001",)
        assert service.last_result == visible

    asyncio.run(scenario())
