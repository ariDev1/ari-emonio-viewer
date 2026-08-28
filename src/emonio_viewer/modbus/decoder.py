import math
import struct
from collections.abc import Sequence

from .register_map import P3_3_0_79, REGISTER_COUNT


class MeasurementDecodeError(ValueError):
    """Raised when a required Modbus measurement cannot be decoded safely."""


def decode_cdab_float(low_word: int, high_word: int) -> float:
    raw = struct.pack(">HH", high_word, low_word)
    return struct.unpack(">f", raw)[0]


def decode_measurement_block(words: Sequence[int]) -> dict[str, float]:
    if len(words) != REGISTER_COUNT:
        raise MeasurementDecodeError(f"expected {REGISTER_COUNT} registers, got {len(words)}")
    result: dict[str, float] = {}
    for register, field in P3_3_0_79.items():
        value = decode_cdab_float(words[register], words[register + 1])
        if not math.isfinite(value):
            raise MeasurementDecodeError(f"non-finite required value: {field}")
        result[field] = value
    return result
