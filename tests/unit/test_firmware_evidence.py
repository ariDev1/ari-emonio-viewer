from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from emonio_viewer.device_evidence.firmware import (
    FIRMWARE_PROBE_PATHS,
    FirmwareProbeError,
    parse_firmware_version,
    probe_firmware_version,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Version: 3.0.80-release (ger)", "3.0.80-release"),
        ("Name: emonio-63a834\n Version: 3.0.79-release\n", "3.0.79-release"),
        ('{"version": "3.0.80-release"}', "3.0.80-release"),
        ("firmware 1.2.3", None),
        ("no version here", None),
        ("Version: abc", None),
        ("Version: 1.2", None),
        ("Version: ", None),
        ("", None),
        ('"version": 123', None),
    ],
)
def test_parse_firmware_version_contract(text: str, expected: str | None) -> None:
    assert parse_firmware_version(text) == expected


def test_parse_firmware_version_rejects_overlong_candidate() -> None:
    assert parse_firmware_version("Version: " + "9" * 40) is None


def test_probe_paths_start_with_root_device_page() -> None:
    assert FIRMWARE_PROBE_PATHS[0] == "/"
    assert all(path.startswith("/") for path in FIRMWARE_PROBE_PATHS)


def _serve(handler: type[BaseHTTPRequestHandler]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_probe_returns_version_from_device_page() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = (
                b"<html><body>Hardware: Emonio-P3<br>"
                b"Version: 3.0.80-release (ger)</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = _serve(Handler)
    try:
        assert (
            probe_firmware_version("127.0.0.1", port=server.server_port)
            == "3.0.80-release"
        )
    finally:
        server.shutdown()


def test_probe_raises_when_no_version_is_exposed() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<html><body>login</body></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = _serve(Handler)
    try:
        with pytest.raises(FirmwareProbeError):
            probe_firmware_version("127.0.0.1", port=server.server_port)
    finally:
        server.shutdown()


def test_probe_raises_when_device_is_unreachable() -> None:
    with pytest.raises(FirmwareProbeError):
        probe_firmware_version("127.0.0.1", port=1, timeout_s=0.5)


def test_scope_extractor_agrees_with_evidence_parser() -> None:
    from emonio_viewer.device_evidence.firmware import (
        FIRMWARE_PROBE_PATHS,
        parse_firmware_version,
    )
    from emonio_viewer.scope.client import (
        _FIRMWARE_PROBE_PATHS as SCOPE_PATHS,
        extract_firmware_version,
    )

    assert tuple(SCOPE_PATHS) == tuple(FIRMWARE_PROBE_PATHS)
    corpus = [
        "Version: 3.0.80-release (ger)",
        "Name: emonio-63a834\n Version: 3.0.79-release\n",
        '{"version": "3.0.80-release"}',
        "no version here",
        "Version: abc",
        "Version: 1.2",
        "",
    ]
    for text in corpus:
        assert extract_firmware_version(text) == parse_firmware_version(text)


def test_scope_status_carries_firmware_evidence() -> None:
    import asyncio

    from emonio_viewer.scope.service import ScopeService
    from emonio_viewer.scope.model import ScopeSessionState

    async def scenario() -> None:
        class VersionClient:
            async def fetch_firmware(self) -> str:
                return "3.0.80-release"

            async def close(self) -> None:
                pass

        async def factory(_host: str, _user: str, _password: str):
            return VersionClient()

        service = ScopeService(client_factory=factory, interval_s=1000.0)  # type: ignore[arg-type]
        await service.start("emonio-63a834", "host", "user", "pass")
        status = service.status("emonio-63a834")
        assert status.firmware == "3.0.80-release"
        assert status.firmware_detail == "OBSERVED_VIA_SCOPE_SESSION"
        assert status.as_dict()["firmware"] == "3.0.80-release"
        await service.close()

    asyncio.run(scenario())


def test_scope_status_records_firmware_failure_detail() -> None:
    import asyncio

    from emonio_viewer.scope.client import ScopeClientError
    from emonio_viewer.scope.service import ScopeService

    async def scenario() -> None:
        class FailingClient:
            async def fetch_firmware(self) -> str:
                raise ScopeClientError("no Emonio firmware version found (/: no version)")

            async def close(self) -> None:
                pass

        async def factory(_host: str, _user: str, _password: str):
            return FailingClient()

        service = ScopeService(client_factory=factory, interval_s=1000.0)  # type: ignore[arg-type]
        await service.start("emonio-63a834", "host", "user", "pass")
        status = service.status("emonio-63a834")
        assert status.firmware is None
        assert status.firmware_detail is not None and "VERSION" in status.firmware_detail.upper()
        await service.close()

    asyncio.run(scenario())


def test_connector_probe_failure_falls_back_to_unknown() -> None:
    from emonio_viewer.acquisition.connector import DeviceConnector

    async def scenario() -> None:
        connector = DeviceConnector.__new__(DeviceConnector)
        with patch(
            "emonio_viewer.acquisition.connector.probe_firmware_version",
            side_effect=FirmwareProbeError("nope"),
        ):
            assert await connector._probe_firmware_version("192.0.2.10") == "unknown"
        with patch(
            "emonio_viewer.acquisition.connector.probe_firmware_version",
            side_effect=RuntimeError("boom"),
        ):
            assert await connector._probe_firmware_version("192.0.2.10") == "unknown"

    import asyncio

    asyncio.run(scenario())


class _StubGetContext:
    def __init__(self, status: int, body: bytes) -> None:
        self._status = status
        self._body = body

    async def __aenter__(self):
        response = self
        response.status = self._status
        return response

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def read(self) -> bytes:
        return self._body


class _StubSession:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self._status = status
        self._body = body
        self.requests: list[str] = []

    def get(self, url: str, **kwargs: object) -> _StubGetContext:
        self.requests.append(url)
        return _StubGetContext(self._status, self._body)


class _StubWs:
    closed = False


def _stub_client(body: bytes, *, status: int = 200):
    from emonio_viewer.scope.client import EmonioScopeClient

    client = EmonioScopeClient.__new__(EmonioScopeClient)
    client._session = _StubSession(status, body)
    client._ws = _StubWs()
    client._base = "http://192.0.2.10"
    client._closed = False
    return client


def test_scope_client_fetch_firmware_reads_device_page() -> None:
    import asyncio

    async def scenario() -> None:
        client = _stub_client(b"Hardware: Emonio-P3<br>Version: 3.0.80-release (ger)")
        assert await client.fetch_firmware() == "3.0.80-release"

    asyncio.run(scenario())


def test_scope_client_fetch_firmware_raises_when_absent() -> None:
    import asyncio

    from emonio_viewer.scope.client import ScopeClientError

    async def scenario() -> None:
        client = _stub_client(b"<html>login</html>")
        with pytest.raises(ScopeClientError):
            await client.fetch_firmware()

    asyncio.run(scenario())


def test_scope_service_reports_firmware_to_sink_on_start() -> None:
    import asyncio

    from emonio_viewer.scope.service import ScopeService
    from emonio_viewer.scope.model import ScopeSessionState

    async def scenario() -> None:
        seen: list[tuple[str, str]] = []

        class SinkClient:
            async def fetch_firmware(self) -> str:
                return "3.0.80-release"

            async def capture_once(self, **kwargs: object):
                raise AssertionError("not used")

            async def close(self) -> None:
                pass

        async def factory(_host: str, _user: str, _password: str):
            return SinkClient()

        service = ScopeService(
            client_factory=factory,  # type: ignore[arg-type]
            interval_s=1000.0,
            firmware_sink=lambda device_id, version: seen.append((device_id, version)),
        )
        status = await service.start("emonio-63a834", "host", "user", "pass")
        assert status.state is ScopeSessionState.LIVE
        assert seen == [("emonio-63a834", "3.0.80-release")]
        await service.close()

    asyncio.run(scenario())


def test_scope_service_start_survives_firmware_failure() -> None:
    import asyncio

    from emonio_viewer.scope.client import ScopeClientError
    from emonio_viewer.scope.service import ScopeService
    from emonio_viewer.scope.model import ScopeSessionState

    async def scenario() -> None:
        seen: list[tuple[str, str]] = []

        class FailingClient:
            async def fetch_firmware(self) -> str:
                raise ScopeClientError("no version")

            async def close(self) -> None:
                pass

        async def factory(_host: str, _user: str, _password: str):
            return FailingClient()

        service = ScopeService(
            client_factory=factory,  # type: ignore[arg-type]
            interval_s=1000.0,
            firmware_sink=lambda device_id, version: seen.append((device_id, version)),
        )
        status = await service.start("emonio-63a834", "host", "user", "pass")
        assert status.state is ScopeSessionState.LIVE
        assert seen == []
        await service.close()

    asyncio.run(scenario())


def _device_config(**overrides: object):
    from emonio_viewer.config.model import DeviceConfig

    values: dict[str, object] = {
        "id": "emonio-63a834",
        "name": "emonio-63a834",
        "host": "192.0.2.10",
        "firmware_version": "unknown",
    }
    values.update(overrides)
    return DeviceConfig(**values)  # type: ignore[arg-type]


def test_coordinator_upgrades_unknown_firmware_only() -> None:
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    coordinator = AcquisitionCoordinator(
        (
            _device_config(id="unknown-device"),
            _device_config(id="known-device", firmware_version="3.0.79-release"),
        ),
        RuntimeStore(),
        RuntimeEventBus(),
    )
    assert coordinator.update_device_firmware("unknown-device", "3.0.80-release") is True
    configs = {device.id: device for device in coordinator.device_configs()}
    assert configs["unknown-device"].firmware_version == "3.0.80-release"
    assert (
        coordinator._workers["unknown-device"].device.firmware_version
        == "3.0.80-release"
    )
    assert coordinator.update_device_firmware("unknown-device", "9.9.9") is False
    assert coordinator.update_device_firmware("known-device", "9.9.9") is False
    assert configs["known-device"].firmware_version == "3.0.79-release"
    assert coordinator.update_device_firmware("missing-device", "3.0.80-release") is False
    assert coordinator.update_device_firmware("unknown-device", "") is False


def test_registry_update_firmware_persists_upgrade_only(tmp_path) -> None:
    from emonio_viewer.config.device_registry import RememberedDeviceRegistry

    registry = RememberedDeviceRegistry(tmp_path / "remembered-devices.json")
    registry.remember(_device_config(id="unknown-device", host="192.0.2.10"))
    registry.remember(
        _device_config(
            id="known-device", host="192.0.2.11", firmware_version="3.0.79-release"
        )
    )
    assert registry.update_firmware("unknown-device", "3.0.80-release") is True
    assert registry.update_firmware("known-device", "9.9.9") is False
    assert registry.update_firmware("missing-device", "3.0.80-release") is False
    reloaded = {device.id: device for device in registry.load()}
    assert reloaded["unknown-device"].firmware_version == "3.0.80-release"
    assert reloaded["known-device"].firmware_version == "3.0.79-release"


def test_connector_scope_sink_upgrades_live_and_persisted_config(tmp_path) -> None:
    from emonio_viewer.acquisition.connector import DeviceConnector
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.config.device_registry import RememberedDeviceRegistry
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    registry = RememberedDeviceRegistry(tmp_path / "remembered-devices.json")
    registry.remember(_device_config())
    coordinator = AcquisitionCoordinator(
        (_device_config(),), RuntimeStore(), RuntimeEventBus()
    )
    connector = DeviceConnector(coordinator, recording=None, registry=registry)
    connector.note_device_firmware("emonio-63a834", "3.0.80-release")
    configs = {device.id: device for device in coordinator.device_configs()}
    assert configs["emonio-63a834"].firmware_version == "3.0.80-release"
    reloaded = {device.id: device for device in registry.load()}
    assert reloaded["emonio-63a834"].firmware_version == "3.0.80-release"
    # Sink never raises, even for unknown devices or missing registry.
    connector.note_device_firmware("missing-device", "3.0.80-release")
    DeviceConnector(coordinator, recording=None).note_device_firmware(
        "emonio-63a834", "3.0.80-release"
    )
