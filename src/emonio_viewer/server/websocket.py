import asyncio
from queue import Empty

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from emonio_viewer.measurement.model import MeasurementSample

from .api import sample_to_json
from .keys import EVENT_BUS_KEY, RUNTIME_STORE_KEY


async def websocket_measurements(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    bus = request.app[EVENT_BUS_KEY]
    store = request.app[RUNTIME_STORE_KEY]
    subscriber = bus.subscribe(maxsize=4)
    try:
        while not ws.closed:
            try:
                event = await asyncio.to_thread(subscriber.get, True, 0.5)
            except Empty:
                continue
            if not isinstance(event, MeasurementSample):
                continue
            snapshot = store.get_device(event.identity.device_id)
            try:
                await ws.send_json(sample_to_json(event, snapshot))
            except ClientConnectionResetError:
                break
    finally:
        bus.unsubscribe(subscriber)
    return ws
