import time

import pytest

from emonio_viewer.acquisition.coordinator import AcquisitionCoordinator
from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from tests.fixtures.real_device_samples import PHASE_A_WORDS, PHASE_B_WORDS, PHASE_C_WORDS, TOTAL_WORDS
from tests.integration.fake_emonio import FakeEmonioServer


class ManualClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def monotonic_clock() -> ManualClock:
    return ManualClock()


def _loaded_server() -> FakeEmonioServer:
    server = FakeEmonioServer()
    for base, words in (
        (0, PHASE_A_WORDS),
        (100, PHASE_B_WORDS),
        (200, PHASE_C_WORDS),
        (300, TOTAL_WORDS),
    ):
        server.set_block(base, words)
    server.start()
    return server


@pytest.fixture
def two_fake_emonios():
    servers = (_loaded_server(), _loaded_server())
    try:
        yield servers
    finally:
        for server in servers:
            server.stop()


@pytest.fixture
def two_device_configs(two_fake_emonios) -> tuple[DeviceConfig, DeviceConfig]:
    first, second = two_fake_emonios
    return (
        DeviceConfig(
            id="emonio-a",
            name="emonio-a",
            host=first.host,
            port=first.port,
            poll_interval_s=0.05,
            timeout_s=0.1,
            firmware_version="3.0.79-release",
        ),
        DeviceConfig(
            id="emonio-b",
            name="emonio-b",
            host=second.host,
            port=second.port,
            poll_interval_s=0.05,
            timeout_s=0.1,
            firmware_version="3.0.79-release",
        ),
    )


def build_coordinator(device_configs, _servers=None, clock=time.monotonic):
    store = RuntimeStore(clock=clock)
    bus = RuntimeEventBus()
    coordinator = AcquisitionCoordinator(tuple(device_configs), store, bus)
    return coordinator, store


def wait_until(predicate, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_failed_device_does_not_stop_healthy_device(two_fake_emonios, two_device_configs) -> None:
    healthy, failing = two_fake_emonios
    failing.fail_all_reads(mode="timeout")
    coordinator, store = build_coordinator(two_device_configs, two_fake_emonios)
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(two_device_configs[0].id).cycles_valid >= 2)
        wait_until(lambda: store.get_device(two_device_configs[1].id).cycles_invalid >= 1)
        healthy_snapshot = store.get_device(two_device_configs[0].id)
        failing_snapshot = store.get_device(two_device_configs[1].id)
    finally:
        coordinator.stop()
    assert healthy_snapshot.cycles_valid >= 2
    assert failing_snapshot.cycles_invalid >= 1


def test_stale_state_keeps_last_good_measurement(fake_emonio, device_config, monotonic_clock) -> None:
    coordinator, store = build_coordinator([device_config], [fake_emonio], clock=monotonic_clock)
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device_config.id).last_sample is not None)
        before = store.get_device(device_config.id)
        assert before.last_sample is not None
        last_p = before.last_sample.phase_b.measurement.p
        fake_emonio.stop()
        monotonic_clock.advance(device_config.poll_interval_s * 3 + 0.001)
        after = store.get_device(device_config.id)
    finally:
        coordinator.stop()
    assert after.state.value == "STALE"
    assert after.last_sample is not None
    assert after.last_sample.phase_b.measurement.p == last_p
    assert after.sample_age_s is not None
    assert after.sample_age_s > device_config.poll_interval_s * 3
