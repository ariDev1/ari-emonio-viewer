from dataclasses import FrozenInstanceError
import pytest

from emonio_viewer.measurement.model import PhaseMeasurement


def test_phase_measurement_preserves_negative_signs_and_unsigned_irms() -> None:
    phase = PhaseMeasurement(
        vrms=233.231094,
        irms=4.35338259,
        p=-58.4114113,
        q=-1013.66266,
        s=1015.34424,
        frequency=49.9600334,
        energy=-20.2668419,
        pf=-0.0575286783,
    )
    assert phase.p < 0
    assert phase.q < 0
    assert phase.pf < 0
    assert phase.energy < 0
    assert phase.irms > 0


def test_phase_measurement_is_immutable() -> None:
    phase = PhaseMeasurement(230, 1, 100, 20, 102, 50, 1, 0.98)
    with pytest.raises(FrozenInstanceError):
        phase.p = 10  # type: ignore[misc]
