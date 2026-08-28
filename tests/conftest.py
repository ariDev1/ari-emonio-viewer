from datetime import datetime, timezone

import pytest

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.measurement.model import (
    AcquisitionMetadata,
    BlockState,
    MeasurementIdentity,
    MeasurementSample,
    PhaseMeasurement,
    RawBlockEvidence,
    SampleTiming,
)
from emonio_viewer.measurement.quadrant import classify_flow, classify_quadrant
from emonio_viewer.measurement.validation import Tolerances, validate_complete_measurement
from emonio_viewer.modbus.decoder import decode_measurement_block
from tests.fixtures.real_device_samples import PHASE_A_WORDS, PHASE_B_WORDS, PHASE_C_WORDS, TOTAL_WORDS
from tests.integration.fake_emonio import FakeEmonioServer


@pytest.fixture
def fake_emonio():
    server = FakeEmonioServer()
    for base, words in (
        (0, PHASE_A_WORDS),
        (100, PHASE_B_WORDS),
        (200, PHASE_C_WORDS),
        (300, TOTAL_WORDS),
    ):
        server.set_block(base, words)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def device_config(fake_emonio):
    return DeviceConfig(
        id="emonio-example",
        name="emonio-example",
        host=fake_emonio.host,
        port=fake_emonio.port,
        unit_id=1,
        poll_interval_s=0.05,
        timeout_s=0.1,
        enabled=True,
        firmware_version="3.0.79-release",
    )


def _block(base, words):
    values = decode_measurement_block(words)
    measurement = PhaseMeasurement(**values)
    return BlockState(
        measurement=measurement,
        quadrant=classify_quadrant(measurement.p, measurement.q),
        flow=classify_flow(measurement.p),
        acquired_utc=datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc),
        raw=RawBlockEvidence(base_register=base, words=tuple(words)),
    )


@pytest.fixture
def real_sample():
    a = _block(0, PHASE_A_WORDS)
    b = _block(100, PHASE_B_WORDS)
    c = _block(200, PHASE_C_WORDS)
    total = _block(300, TOTAL_WORDS)
    validation = validate_complete_measurement(
        phase_a=a.measurement,
        phase_b=b.measurement,
        phase_c=c.measurement,
        total=total.measurement,
        tolerances=Tolerances(),
    )
    when = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)
    return MeasurementSample(
        identity=MeasurementIdentity(
            1,
            "emonio-example",
            "emonio-example",
            "192.0.2.11",
            "3.0.79-release",
            "MODBUS_TCP",
            1,
        ),
        timing=SampleTiming(when, when, 1_000_000_000, 1_100_000_000, 100.0),
        acquisition=AcquisitionMetadata(0.0),
        phase_a=a,
        phase_b=b,
        phase_c=c,
        total=total,
        quality=validation.quality,
        warnings=validation.warnings,
        derived=validation.derived,
    )
