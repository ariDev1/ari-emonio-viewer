import math
from emonio_viewer.modbus.decoder import decode_cdab_float, decode_measurement_block
from tests.fixtures.real_device_samples import PHASE_B_WORDS


def test_decodes_real_phase_b_negative_watt_fixture() -> None:
    assert math.isclose(decode_cdab_float(0xA549, 0xC269), -58.4114113, rel_tol=1e-7)


def test_decodes_complete_phase_b_without_sign_changes() -> None:
    values = decode_measurement_block(PHASE_B_WORDS)
    assert math.isclose(values["p"], -58.4114113, rel_tol=1e-7)
    assert math.isclose(values["q"], -1013.66266, rel_tol=1e-7)
    assert math.isclose(values["s"], 1015.34424, rel_tol=1e-7)
    assert math.isclose(values["pf"], -0.0575286783, rel_tol=1e-7)
