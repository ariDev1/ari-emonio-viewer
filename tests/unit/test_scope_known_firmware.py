from __future__ import annotations

import asyncio

from emonio_viewer.scope.service import ScopeService


class _Client:
    def __init__(self) -> None:
        self.fetch_calls = 0
        self.closed = False

    async def fetch_firmware(self) -> str:
        self.fetch_calls += 1
        raise AssertionError("scope HTTP firmware probe must not run when device firmware is known")

    async def capture_once(self, *, sequence: int, listen_s: float = 2.0):
        await asyncio.sleep(3600)

    async def close(self) -> None:
        self.closed = True


def test_scope_uses_known_device_firmware_without_http_rediscovery() -> None:
    async def exercise():
        client = _Client()

        async def factory(_host: str, _username: str, _password: str):
            return client

        service = ScopeService(
            client_factory=factory,
            firmware_source=lambda device_id: "3.0.80-release" if device_id == "emonio-a" else None,
        )
        status = await service.start("emonio-a", "host", "user", "password")
        await service.close()
        return status, client

    status, client = asyncio.run(exercise())

    assert status.firmware == "3.0.80-release"
    assert status.firmware_detail == "KNOWN_DEVICE_EVIDENCE"
    assert client.fetch_calls == 0
    assert client.closed is True
