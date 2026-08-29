from __future__ import annotations

import math
import struct

from emonio_viewer.device_evidence.modbus import (
    ERROR_FLAGS,
    WARNING_FLAGS,
    decode_energy_flow_registers,
    decode_status_flags,
)


def _cdab_words(value: float) -> tuple[int, int]:
    high, low = struct.unpack(">HH", struct.pack(">f", value))
    return low, high


def test_energy_flow_decoder_preserves_emonio_cdab_float_values() -> None:
    words = _cdab_words(12.5) + _cdab_words(3.25)
    energy_in, energy_out = decode_energy_flow_registers(words)
    assert math.isclose(energy_in, 12.5)
    assert math.isclose(energy_out, 3.25)


def test_status_decoder_exposes_raw_bits_and_documented_names_without_inference() -> None:
    raw = (1 << 2) | (1 << 7) | (1 << 14)
    assert decode_status_flags(raw, ERROR_FLAGS) == (
        "FS_FULL",
        "WIFI_AUTH_FAILED",
        "SENSOR_DATA_INVALID",
    )
    warning = (1 << 1) | (1 << 4)
    assert decode_status_flags(warning, WARNING_FLAGS) == (
        "FS_LOW",
        "TELEMETRY_DISCONNECTED",
    )
