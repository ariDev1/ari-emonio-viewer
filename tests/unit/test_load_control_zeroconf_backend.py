import asyncio

from emonio_viewer.load_control.discovery_zeroconf import ZeroconfMdnsBackend


class FakeInfo:
    port = 8765
    properties = {
        b"node_id": b"ARI-LOAD-001",
        b"device_class": b"ARI_LOAD_ACTUATOR",
        b"capabilities": b"ACTIVE_LOAD_CONTROL",
        b"p_max_a_w": b"1200.0",
        b"p_max_b_w": b"1200.0",
        b"p_max_c_w": b"1200.0",
        b"ws_path": b"/control",
    }

    def parsed_addresses(self):
        return ["192.168.20.44"]


class FakeAsyncZeroconf:
    def __init__(self) -> None:
        self.zeroconf = object()
        self.resolve_calls = []
        self.closed = False

    async def async_get_service_info(self, service_type, name, timeout):
        self.resolve_calls.append((service_type, name, timeout))
        return FakeInfo()

    async def async_close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, zeroconf, service_type, *, listener) -> None:
        self.cancelled = False
        listener.add_service(zeroconf, service_type, "ari-load-001._ari-emonio-load._tcp.local.")

    async def async_cancel(self) -> None:
        self.cancelled = True


def test_zeroconf_backend_uses_exact_windows_and_closes_resources() -> None:
    async def scenario() -> None:
        aiozc = FakeAsyncZeroconf()
        browsers = []
        sleeps = []

        def browser_factory(*args, **kwargs):
            browser = FakeBrowser(*args, **kwargs)
            browsers.append(browser)
            return browser

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        backend = ZeroconfMdnsBackend(
            aiozc_factory=lambda: aiozc,
            browser_factory=browser_factory,
            sleep=fake_sleep,
        )
        records = await backend.scan(
            service_type="_ari-emonio-load._tcp.local.",
            discovery_window_s=0.25,
            resolve_timeout_s=0.15,
        )

        assert sleeps == [0.25]
        assert aiozc.resolve_calls == [
            (
                "_ari-emonio-load._tcp.local.",
                "ari-load-001._ari-emonio-load._tcp.local.",
                150,
            )
        ]
        assert browsers[0].cancelled is True
        assert aiozc.closed is True
        assert len(records) == 1
        assert records[0].address == "192.168.20.44"
        assert records[0].port == 8765
        assert records[0].properties[b"node_id"] == b"ARI-LOAD-001"

    asyncio.run(scenario())
