from emonio_viewer.modbus.register_map import BLOCK_BASES, P3_3_0_79


def test_verified_map_keeps_var_at_6_and_va_at_8() -> None:
    assert P3_3_0_79[6] == "q"
    assert P3_3_0_79[8] == "s"


def test_block_bases_are_verified_values() -> None:
    assert BLOCK_BASES == {"A": 0, "B": 100, "C": 200, "TOTAL": 300}
