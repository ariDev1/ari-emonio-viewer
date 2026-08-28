from __future__ import annotations

import asyncio
import json
import struct

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from emonio_viewer.scope.client import EmonioScopeClient, ScopeClientError
from emonio_viewer.scope.protocol import FIELD_SAMPLE_COUNT


def _frame(channel: int) -> bytes:
    values = [channel + index / 100.0 for index in range(FIELD_SAMPLE_COUNT)]
    return b"\xe5\xd2\x00" + bytes([channel]) + struct.pack(f"<{FIELD_SAMPLE_COUNT}f", *values)


def _metadata(phase: int) -> str:
    return json.dumps(
        {
            "type": "scope",
            "phase": phase,
            "connected": 1,
            "vrms": 230.0 + phase,
            "irms": 10.0 + phase,
            "freq": 50.0,
            "pf": -0.1 + phase * 0.1,
            "ms": 35.6,
        }
    )


def test_client_uses_field_proven_authenticated_sequence_and_only_scope_ws_payload() -> None:
    async def exercise():
        evidence = {"login": None, "paths": [], "ws_text": []}
        app = web.Application()

        async def login(request: web.Request):
            reader = await request.multipart()
            fields = {}
            while True:
                part = await reader.next()
                if part is None:
                    break
                fields[part.name] = await part.text()
            evidence["login"] = fields
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie("LOGIN_SESSION_KEY", "session-123")
            return response

        async def root(request: web.Request):
            evidence["paths"].append("/")
            return web.Response(text="root")

        async def scope(request: web.Request):
            evidence["paths"].append("/scope")
            return web.Response(text="scope")

        async def websocket(request: web.Request):
            assert request.cookies.get("LOGIN_SESSION_KEY") == "session-123"
            ws = web.WebSocketResponse(compress=True)
            await ws.prepare(request)
            async for message in ws:
                if message.type is web.WSMsgType.TEXT:
                    evidence["ws_text"].append(message.data)
                    for channel in range(6):
                        await ws.send_bytes(_frame(channel))
                    for phase in range(3):
                        await ws.send_str(_metadata(phase))
                    break
            await ws.close()
            return ws

        app.router.add_post("/login", login)
        app.router.add_get("/", root)
        app.router.add_get("/scope", scope)
        app.router.add_get("/ws", websocket)

        async with TestServer(app) as server:
            host = f"127.0.0.1:{server.port}"
            client = await EmonioScopeClient.connect(host, "admin-user", "secret-pass")
            try:
                capture = await client.capture_once(sequence=4)
                private_state = repr(client)
            finally:
                await client.close()
        return evidence, capture, private_state

    evidence, capture, private_state = asyncio.run(exercise())
    assert evidence["login"] == {"USER": "admin-user", "PASS": "secret-pass"}
    assert evidence["paths"] == ["/", "/scope"]
    assert evidence["ws_text"] == ["scope"]
    assert capture.sequence == 4
    assert capture.channel_order == (0, 1, 2, 3, 4, 5)
    assert capture.metadata_order == (0, 1, 2)
    assert capture.channels[0].samples[1] == pytest.approx(0.01, abs=1e-7)
    assert "admin-user" not in private_state
    assert "secret-pass" not in private_state


def test_client_fails_closed_on_incomplete_capture() -> None:
    async def exercise():
        app = web.Application()

        async def login(_request):
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie("LOGIN_SESSION_KEY", "session-123")
            return response

        async def ok(_request):
            return web.Response(text="ok")

        async def websocket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            message = await ws.receive()
            assert message.data == "scope"
            for channel in range(5):
                await ws.send_bytes(_frame(channel))
            for phase in range(3):
                await ws.send_str(_metadata(phase))
            await asyncio.sleep(0.2)
            await ws.close()
            return ws

        app.router.add_post("/login", login)
        app.router.add_get("/", ok)
        app.router.add_get("/scope", ok)
        app.router.add_get("/ws", websocket)

        async with TestServer(app) as server:
            client = await EmonioScopeClient.connect(f"127.0.0.1:{server.port}", "u", "p")
            try:
                with pytest.raises(ScopeClientError, match="incomplete"):
                    await client.capture_once(sequence=1, listen_s=0.3)
            finally:
                await client.close()

    asyncio.run(exercise())


def test_connect_cancellation_closes_new_http_session_and_reraises_cancellation(monkeypatch) -> None:
    import emonio_viewer.scope.client as client_module

    class BlockingResponseContext:
        def __init__(self, entered: asyncio.Event) -> None:
            self.entered = entered

        async def __aenter__(self):
            self.entered.set()
            await asyncio.Event().wait()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class TrackingSession:
        def __init__(self, *args, **kwargs) -> None:
            self.entered = asyncio.Event()
            self.close_calls = 0

        def post(self, *args, **kwargs):
            return BlockingResponseContext(self.entered)

        async def close(self):
            self.close_calls += 1

    sessions = []

    def session_factory(*args, **kwargs):
        session = TrackingSession(*args, **kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(client_module.aiohttp, "ClientSession", session_factory)

    async def exercise():
        task = asyncio.create_task(EmonioScopeClient.connect("127.0.0.1", "u", "p"))
        while not sessions:
            await asyncio.sleep(0)
        await sessions[0].entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert len(sessions) == 1
    assert sessions[0].close_calls == 1



def test_scope_connect_allows_field_observed_slow_local_name_resolution(monkeypatch) -> None:
    async def exercise():
        app = web.Application()

        async def login(_request: web.Request):
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie("LOGIN_SESSION_KEY", "session-123")
            return response

        async def ok(_request: web.Request):
            return web.Response(text="ok")

        async def websocket(request: web.Request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.close()
            return ws

        app.router.add_post("/login", login)
        app.router.add_get("/", ok)
        app.router.add_get("/scope", ok)
        app.router.add_get("/ws", websocket)

        async with TestServer(app) as server:
            loop = asyncio.get_running_loop()
            original_getaddrinfo = loop.getaddrinfo

            async def delayed_getaddrinfo(host, port, *args, **kwargs):
                if host == "emonio-slow.local":
                    await asyncio.sleep(4.2)
                    host = "127.0.0.1"
                return await original_getaddrinfo(host, port, *args, **kwargs)

            monkeypatch.setattr(loop, "getaddrinfo", delayed_getaddrinfo)
            client = await EmonioScopeClient.connect(
                f"emonio-slow.local:{server.port}",
                "u",
                "p",
            )
            await client.close()

    asyncio.run(exercise())
