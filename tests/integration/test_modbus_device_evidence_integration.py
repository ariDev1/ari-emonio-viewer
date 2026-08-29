from __future__ import annotations

import asyncio
import struct

from emonio_viewer.device_evidence.modbus import ModbusDeviceEvidenceReader
from emonio_viewer.device_evidence.service import ModbusDeviceEvidenceService
from emonio_viewer.modbus.transport import ReadOnlyModbusClient


def _cdab_words(value: float) -> tuple[int, int]:
    high, low = struct.unpack(">HH", struct.pack(">f", value))
    return low, high


def _read_values(reader, device):
    client = ReadOnlyModbusClient(
        device.host,
        device.port,
        device.unit_id,
        device.timeout_s,
    )
    try:
        return reader.read(client)
    finally:
        client.close()


def test_reader_uses_only_exact_non_destructive_read_ranges(fake_emonio, device_config) -> None:
    expected = {
        40: (1.25, 0.25),
        140: (2.5, 0.5),
        240: (3.75, 0.75),
        340: (7.5, 1.5),
    }
    for base, (energy_in, energy_out) in expected.items():
        fake_emonio.set_holding_registers(base, _cdab_words(energy_in) + _cdab_words(energy_out))
    fake_emonio.set_holding_registers(1000, ((1 << 2) | (1 << 7), (1 << 1) | (1 << 4)))
    fake_emonio.set_discrete_inputs(0, (True, False, True))

    values = _read_values(ModbusDeviceEvidenceReader(), device_config)

    assert values.energy["A"].energy_in == 1.25
    assert values.energy["TOTAL"].energy_out == 1.5
    assert values.connected == {"A": True, "B": False, "C": True}
    assert values.error_raw == (1 << 2) | (1 << 7)
    assert values.warning_raw == (1 << 1) | (1 << 4)
    assert values.error_flags == ("FS_FULL", "WIFI_AUTH_FAILED")
    assert values.warning_flags == ("FS_LOW", "TELEMETRY_DISCONNECTED")
    assert fake_emonio.requested_reads == [
        (0x03, 40, 4),
        (0x03, 140, 4),
        (0x03, 240, 4),
        (0x03, 340, 4),
        (0x02, 0, 3),
        (0x03, 1000, 2),
    ]
    assert all(
        not (20 <= base <= 30 or 120 <= base <= 130 or 220 <= base <= 230)
        for _, base, _ in fake_emonio.requested_reads
    )


def test_service_caches_last_successful_modbus_evidence(fake_emonio, device_config) -> None:
    for base in (40, 140, 240, 340):
        fake_emonio.set_holding_registers(base, _cdab_words(1.0) + _cdab_words(0.0))
    fake_emonio.set_holding_registers(1000, (0, 0))
    fake_emonio.set_discrete_inputs(0, (True, True, True))
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    coordinator = AcquisitionCoordinator((device_config,), RuntimeStore(), RuntimeEventBus())
    service = ModbusDeviceEvidenceService(
        ModbusDeviceEvidenceReader(),
        coordinator=coordinator,
    )
    coordinator.start()
    try:
        evidence = asyncio.run(service.read(device_config))
    finally:
        coordinator.stop()

    assert service.get(device_config.id) == evidence
    payload = evidence.as_dict()
    assert payload["source"] == "EMONIO_MODBUS_TCP_DEVICE_EVIDENCE"
    assert payload["transport"] == "MODBUS_TCP"
    assert payload["interpretation"] == "DOCUMENTED_DEVICE_VALUES"
    assert payload["values"]["energy"]["A"] == {"kwh_in": 1.0, "kwh_out": 0.0}


def test_reader_keeps_successful_fields_when_one_documented_read_returns_modbus_exception(
    fake_emonio, device_config
) -> None:
    for base in (40, 140, 240, 340):
        fake_emonio.set_holding_registers(base, _cdab_words(float(base)) + _cdab_words(0.5))
    fake_emonio.set_holding_registers(1000, (4, 2))
    fake_emonio.set_discrete_inputs(0, (True, False, True))
    fake_emonio.fail_next_read(140, "exception")

    values = _read_values(ModbusDeviceEvidenceReader(), device_config)

    assert values.read_status == "PARTIAL"
    assert values.energy["A"].energy_in == 40.0
    assert values.energy["B"] is None
    assert values.energy["C"].energy_in == 240.0
    assert values.energy["TOTAL"].energy_in == 340.0
    assert values.connected == {"A": True, "B": False, "C": True}
    assert values.error_raw == 4
    assert values.warning_raw == 2
    assert fake_emonio.requested_reads == [
        (0x03, 40, 4),
        (0x03, 140, 4),
        (0x03, 240, 4),
        (0x03, 340, 4),
        (0x02, 0, 3),
        (0x03, 1000, 2),
    ]

    diagnostics = {item.key: item for item in values.read_diagnostics}
    failed = diagnostics["ENERGY_B"]
    assert failed.function_code == 0x03
    assert failed.address == 140
    assert failed.count == 4
    assert failed.status == "ERROR"
    assert failed.error_type == "ModbusExceptionResponse"
    assert failed.error_detail == "exception code 2"
    assert failed.elapsed_ms >= 0.0
    assert diagnostics["ENERGY_A"].status == "OK"
    assert diagnostics["CONNECTED_ABC"].status == "OK"
    assert diagnostics["STATUS"].status == "OK"


def test_reader_reports_all_probe_failures_without_raising(fake_emonio, device_config) -> None:
    fake_emonio.fail_all_reads("exception")

    values = _read_values(ModbusDeviceEvidenceReader(), device_config)

    assert values.read_status == "FAILED"
    assert values.energy == {"A": None, "B": None, "C": None, "TOTAL": None}
    assert values.connected == {"A": None, "B": None, "C": None}
    assert values.error_raw is None
    assert values.warning_raw is None
    assert values.error_flags is None
    assert values.warning_flags is None
    assert len(values.read_diagnostics) == 6
    assert all(item.status == "ERROR" for item in values.read_diagnostics)
    assert all(item.error_type == "ModbusExceptionResponse" for item in values.read_diagnostics)


def _wait_until(predicate, timeout_s: float = 1.0) -> None:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached before timeout")


def _configure_auxiliary_evidence(fake_emonio) -> None:
    for base in (40, 140, 240, 340):
        fake_emonio.set_holding_registers(base, _cdab_words(float(base)) + _cdab_words(0.5))
    fake_emonio.set_holding_registers(1000, (4, 2))
    fake_emonio.set_discrete_inputs(0, (True, False, True))


def test_service_queues_evidence_on_worker_and_reuses_primary_modbus_connection(
    fake_emonio, device_config
) -> None:
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    _configure_auxiliary_evidence(fake_emonio)
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((device_config,), store, RuntimeEventBus())
    service = ModbusDeviceEvidenceService(
        ModbusDeviceEvidenceReader(),
        coordinator=coordinator,
    )
    coordinator.start()
    try:
        _wait_until(lambda: store.get_device(device_config.id).last_sample is not None)
        evidence = asyncio.run(service.read(device_config))
    finally:
        coordinator.stop()

    assert evidence.read_status == "OBSERVED"
    assert fake_emonio.connection_count == 1
    evidence_reads = [
        (0x03, 40, 4),
        (0x03, 140, 4),
        (0x03, 240, 4),
        (0x03, 340, 4),
        (0x02, 0, 3),
        (0x03, 1000, 2),
    ]
    start = fake_emonio.requested_reads.index(evidence_reads[0])
    assert fake_emonio.requested_reads[start : start + len(evidence_reads)] == evidence_reads
    assert fake_emonio.requested_reads[start - 4 : start] == [
        (0x03, 0, 16),
        (0x03, 100, 16),
        (0x03, 200, 16),
        (0x03, 300, 16),
    ]


def test_transport_reset_stops_remaining_evidence_probes_and_canonical_cycle_reconnects(
    fake_emonio, device_config
) -> None:
    from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
    from emonio_viewer.runtime.events import RuntimeEventBus
    from emonio_viewer.runtime.store import RuntimeStore

    _configure_auxiliary_evidence(fake_emonio)
    store = RuntimeStore()
    coordinator = AcquisitionCoordinator((device_config,), store, RuntimeEventBus())
    service = ModbusDeviceEvidenceService(
        ModbusDeviceEvidenceReader(),
        coordinator=coordinator,
    )
    coordinator.start()
    try:
        _wait_until(lambda: store.get_device(device_config.id).last_sample is not None)
        cycle_before = store.get_device(device_config.id).last_sample.identity.cycle_id
        fake_emonio.fail_next_read(140, "reset")
        evidence = asyncio.run(service.read(device_config))
        cycle_at_evidence = store.get_device(device_config.id).last_sample.identity.cycle_id
        assert cycle_at_evidence > cycle_before
        _wait_until(
            lambda: (
                fake_emonio.connection_count >= 2
                and store.get_device(device_config.id).last_sample is not None
                and store.get_device(device_config.id).last_sample.identity.cycle_id
                > cycle_at_evidence
            ),
            timeout_s=1.5,
        )
    finally:
        coordinator.stop()

    diagnostics = {item.key: item for item in evidence.values.read_diagnostics}
    assert diagnostics["ENERGY_A"].status == "OK"
    assert diagnostics["ENERGY_B"].status == "ERROR"
    assert diagnostics["ENERGY_B"].error_type in {"ConnectionError", "ConnectionResetError"}
    assert diagnostics["ENERGY_C"].status == "SKIPPED"
    assert diagnostics["ENERGY_TOTAL"].status == "SKIPPED"
    assert diagnostics["CONNECTED_ABC"].status == "SKIPPED"
    assert diagnostics["STATUS"].status == "SKIPPED"
    assert fake_emonio.connection_count == 2

    evidence_start = fake_emonio.requested_bases.index(40)
    assert fake_emonio.requested_bases[evidence_start : evidence_start + 2] == [40, 140]
    assert 240 not in fake_emonio.requested_bases[evidence_start : evidence_start + 6]
    assert fake_emonio.requested_bases[-4:] == [0, 100, 200, 300]
