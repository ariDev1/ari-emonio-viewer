from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.device_evidence.model import (
    EnergyFlowEvidence,
    ModbusDeviceEvidence,
    ModbusDeviceEvidenceValues,
    ModbusEvidenceReadDiagnostic,
)
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app


class FakeRecordingManager:
    def active_recordings(self):
        return ()


class FakeEvidenceService:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def get(self, device_id):
        self.calls.append(("get", device_id))
        return self.evidence

    async def read(self, device):
        self.calls.append(("read", device.id, device.host))
        return self.evidence


def _evidence(device_id):
    values = ModbusDeviceEvidenceValues(
        energy={phase: EnergyFlowEvidence(1.0, 0.25) for phase in ("A", "B", "C", "TOTAL")},
        connected={"A": True, "B": False, "C": True},
        error_raw=4,
        warning_raw=2,
        error_flags=("FS_FULL",),
        warning_flags=("FS_LOW",),
        read_diagnostics=(
            ModbusEvidenceReadDiagnostic("ENERGY_A", 0x03, 40, 4, "OK", 1.25),
            ModbusEvidenceReadDiagnostic("ENERGY_B", 0x03, 140, 4, "OK", 1.5),
            ModbusEvidenceReadDiagnostic("ENERGY_C", 0x03, 240, 4, "OK", 1.75),
            ModbusEvidenceReadDiagnostic("ENERGY_TOTAL", 0x03, 340, 4, "OK", 2.0),
            ModbusEvidenceReadDiagnostic("CONNECTED_ABC", 0x02, 0, 3, "OK", 0.75),
            ModbusEvidenceReadDiagnostic("STATUS", 0x03, 1000, 2, "OK", 0.5),
        ),
    )
    return ModbusDeviceEvidence(
        device_id,
        datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc),
        values,
    )


def _app(tmp_path, real_sample, device_config, service):
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    return create_app(
        config,
        store,
        RuntimeEventBus(),
        FakeRecordingManager(),
        frontend,
        modbus_evidence=service,
    )


async def _request(app, method, path):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path)
            return response.status, await response.json()


def test_modbus_evidence_get_returns_cached_evidence_without_device_read(
    tmp_path, real_sample, device_config
) -> None:
    service = FakeEvidenceService(_evidence(device_config.id))
    app = _app(tmp_path, real_sample, device_config, service)
    status, payload = asyncio.run(
        _request(app, "GET", f"/api/v1/devices/{device_config.id}/modbus-evidence")
    )
    assert status == 200
    assert payload["status"] == "OBSERVED"
    assert payload["evidence"]["values"]["error_raw"] == 4
    assert service.calls == [("get", device_config.id)]


def test_modbus_evidence_read_uses_selected_device_config_and_returns_observation(
    tmp_path, real_sample, device_config
) -> None:
    service = FakeEvidenceService(_evidence(device_config.id))
    app = _app(tmp_path, real_sample, device_config, service)
    status, payload = asyncio.run(
        _request(app, "POST", f"/api/v1/devices/{device_config.id}/modbus-evidence/read")
    )
    assert status == 200
    assert payload["status"] == "OBSERVED"
    assert payload["evidence"]["values"]["connected"] == {"A": True, "B": False, "C": True}
    assert service.calls == [("read", device_config.id, device_config.host)]


def test_modbus_evidence_read_returns_partial_diagnostic_observation_without_502(
    tmp_path, real_sample, device_config
) -> None:
    values = ModbusDeviceEvidenceValues(
        energy={
            "A": EnergyFlowEvidence(1.0, 0.25),
            "B": None,
            "C": EnergyFlowEvidence(3.0, 0.75),
            "TOTAL": EnergyFlowEvidence(4.0, 1.0),
        },
        connected={"A": True, "B": False, "C": True},
        error_raw=0,
        warning_raw=0,
        error_flags=(),
        warning_flags=(),
        read_diagnostics=(
            ModbusEvidenceReadDiagnostic("ENERGY_A", 0x03, 40, 4, "OK", 1.0),
            ModbusEvidenceReadDiagnostic(
                "ENERGY_B",
                0x03,
                140,
                4,
                "ERROR",
                8.1,
                "ModbusExceptionResponse",
                "exception code 2",
            ),
            ModbusEvidenceReadDiagnostic("ENERGY_C", 0x03, 240, 4, "OK", 1.1),
            ModbusEvidenceReadDiagnostic("ENERGY_TOTAL", 0x03, 340, 4, "OK", 1.2),
            ModbusEvidenceReadDiagnostic("CONNECTED_ABC", 0x02, 0, 3, "OK", 0.8),
            ModbusEvidenceReadDiagnostic("STATUS", 0x03, 1000, 2, "OK", 0.9),
        ),
    )
    evidence = ModbusDeviceEvidence(
        device_config.id,
        datetime(2026, 8, 28, 18, 5, tzinfo=timezone.utc),
        values,
    )
    service = FakeEvidenceService(evidence)
    app = _app(tmp_path, real_sample, device_config, service)

    status, payload = asyncio.run(
        _request(app, "POST", f"/api/v1/devices/{device_config.id}/modbus-evidence/read")
    )

    assert status == 200
    assert payload["status"] == "PARTIAL"
    assert payload["evidence"]["read_status"] == "PARTIAL"
    assert payload["evidence"]["values"]["energy"]["B"] is None
    failed = payload["evidence"]["values"]["read_diagnostics"][1]
    assert failed == {
        "key": "ENERGY_B",
        "function_code": 3,
        "address": 140,
        "count": 4,
        "status": "ERROR",
        "elapsed_ms": 8.1,
        "error_type": "ModbusExceptionResponse",
        "error_detail": "exception code 2",
    }
