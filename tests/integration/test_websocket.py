import asyncio
from pathlib import Path

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app


class NoopRecordingManager:
    pass


@pytest.fixture
def app_bus_and_sample(tmp_path, real_sample, device_config):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(
        ViewerConfig(device_config.id),
        RecordingConfig(10.0),
        (device_config,),
    )
    app = create_app(config, store, bus, NoopRecordingManager(), frontend)
    return app, bus, real_sample


async def websocket_case(app, bus, real_sample):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            ws = await client.ws_connect("/ws/v1/measurements")
            bus.publish(real_sample)
            message = await ws.receive(timeout=1.0)
            assert message.type is WSMsgType.TEXT
            payload = message.json()
            await ws.close()
            return payload


def test_websocket_preserves_negative_power_signs(app_bus_and_sample) -> None:
    app, bus, real_sample = app_bus_and_sample
    payload = asyncio.run(websocket_case(app, bus, real_sample))
    phase_b = payload["sample"]["phase_b"]
    assert phase_b["p"] == real_sample.phase_b.measurement.p
    assert phase_b["q"] == real_sample.phase_b.measurement.q
    assert phase_b["pf"] == real_sample.phase_b.measurement.pf
    assert phase_b["quadrant"] == "Q3"
    assert phase_b["flow"] == "NEGATIVE_FLOW"


def test_websocket_connection_reset_during_send_is_clean_disconnect(monkeypatch, real_sample, device_config) -> None:
    from queue import Queue
    from types import SimpleNamespace

    from aiohttp.client_exceptions import ClientConnectionResetError

    from emonio_viewer.runtime.store import RuntimeStore
    from emonio_viewer.server import websocket as websocket_module
    from emonio_viewer.server.keys import EVENT_BUS_KEY, RUNTIME_STORE_KEY

    class ResettingWebSocket:
        closed = False

        async def prepare(self, _request):
            return self

        async def send_json(self, _payload):
            raise ClientConnectionResetError("Cannot write to closing transport")

    class OneEventBus:
        def __init__(self):
            self.subscriber = Queue(maxsize=4)
            self.subscriber.put_nowait(real_sample)
            self.unsubscribed = False

        def subscribe(self, maxsize=4):
            assert maxsize == 4
            return self.subscriber

        def unsubscribe(self, subscriber):
            assert subscriber is self.subscriber
            self.unsubscribed = True

    ws = ResettingWebSocket()
    bus = OneEventBus()
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    request = SimpleNamespace(app={EVENT_BUS_KEY: bus, RUNTIME_STORE_KEY: store})

    monkeypatch.setattr(websocket_module.web, "WebSocketResponse", lambda heartbeat: ws)

    result = asyncio.run(websocket_module.websocket_measurements(request))

    assert result is ws
    assert bus.unsubscribed is True


def test_websocket_unexpected_send_error_is_not_hidden(monkeypatch, real_sample, device_config) -> None:
    from queue import Queue
    from types import SimpleNamespace

    from emonio_viewer.runtime.store import RuntimeStore
    from emonio_viewer.server import websocket as websocket_module
    from emonio_viewer.server.keys import EVENT_BUS_KEY, RUNTIME_STORE_KEY

    class BrokenWebSocket:
        closed = False

        async def prepare(self, _request):
            return self

        async def send_json(self, _payload):
            raise RuntimeError("unexpected websocket defect")

    class OneEventBus:
        def __init__(self):
            self.subscriber = Queue(maxsize=4)
            self.subscriber.put_nowait(real_sample)
            self.unsubscribed = False

        def subscribe(self, maxsize=4):
            assert maxsize == 4
            return self.subscriber

        def unsubscribe(self, subscriber):
            assert subscriber is self.subscriber
            self.unsubscribed = True

    ws = BrokenWebSocket()
    bus = OneEventBus()
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    request = SimpleNamespace(app={EVENT_BUS_KEY: bus, RUNTIME_STORE_KEY: store})

    monkeypatch.setattr(websocket_module.web, "WebSocketResponse", lambda heartbeat: ws)

    with pytest.raises(RuntimeError, match="unexpected websocket defect"):
        asyncio.run(websocket_module.websocket_measurements(request))

    assert bus.unsubscribed is True
