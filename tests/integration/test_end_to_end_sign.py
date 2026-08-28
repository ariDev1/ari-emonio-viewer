import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.acquisition.worker import AcquisitionWorker
from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.modbus.transport import ReadOnlyModbusClient
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app


class NoopRecordingManager:
    pass


async def read_device_json(app, device_id: str):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.get(f"/api/v1/devices/{device_id}")
            assert response.status == 200
            return await response.json()


def test_raw_modbus_to_http_preserves_negative_phase_b_signs(tmp_path, fake_emonio, device_config) -> None:
    client = ReadOnlyModbusClient(
        device_config.host,
        device_config.port,
        device_config.unit_id,
        device_config.timeout_s,
    )
    worker = AcquisitionWorker(device_config, client)
    sample = worker.run_cycle(1)
    client.close()

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    app = create_app(config, store, bus, NoopRecordingManager(), frontend)

    payload = asyncio.run(read_device_json(app, device_config.id))
    phase_b = payload["sample"]["phase_b"]
    assert phase_b["p"] < 0
    assert phase_b["q"] < 0
    assert phase_b["pf"] < 0
    assert phase_b["quadrant"] == "Q3"
