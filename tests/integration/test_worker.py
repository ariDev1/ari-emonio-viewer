import pytest

from emonio_viewer.acquisition.worker import AcquisitionCycleError, AcquisitionWorker
from emonio_viewer.modbus.transport import ReadOnlyModbusClient


def build_worker(fake_emonio, device_config):
    client = ReadOnlyModbusClient(
        device_config.host,
        device_config.port,
        device_config.unit_id,
        device_config.timeout_s,
    )
    return AcquisitionWorker(device_config, client)


def test_one_cycle_reads_a_b_c_total_and_publishes_one_complete_sample(fake_emonio, device_config) -> None:
    worker = build_worker(fake_emonio, device_config)
    sample = worker.run_cycle(cycle_id=1)
    assert sample.identity.cycle_id == 1
    assert sample.phase_b.measurement.p < 0
    assert sample.phase_b.measurement.q < 0
    assert sample.phase_b.measurement.s > 0
    assert fake_emonio.requested_bases == [0, 100, 200, 300]


def test_timeout_in_c_rejects_entire_cycle_and_closes_connection(fake_emonio, device_config) -> None:
    fake_emonio.fail_next_read(base=200, mode="timeout")
    worker = build_worker(fake_emonio, device_config)
    with pytest.raises(AcquisitionCycleError, match="C"):
        worker.run_cycle(cycle_id=1)
    assert worker.client_is_connected is False


def test_successive_cycles_reuse_one_tcp_connection(fake_emonio, device_config) -> None:
    worker = build_worker(fake_emonio, device_config)
    worker.run_cycle(1)
    worker.run_cycle(2)
    assert fake_emonio.connection_count == 1
    assert fake_emonio.request_count == 8


def test_failed_cycle_does_not_retry_inside_same_cycle(fake_emonio, device_config) -> None:
    fake_emonio.fail_next_read(base=200, mode="exception")
    worker = build_worker(fake_emonio, device_config)
    with pytest.raises(AcquisitionCycleError):
        worker.run_cycle(1)
    assert fake_emonio.requested_bases == [0, 100, 200]
    sample = worker.run_cycle(2)
    assert sample.identity.cycle_id == 2
    assert fake_emonio.connection_count == 2
    assert fake_emonio.requested_bases[-4:] == [0, 100, 200, 300]
