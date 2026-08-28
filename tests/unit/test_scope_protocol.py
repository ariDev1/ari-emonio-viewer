from __future__ import annotations

import json
import math
import struct

import pytest

from emonio_viewer.scope.protocol import (
    FIELD_FRAME_BYTES,
    FIELD_SAMPLE_COUNT,
    build_capture,
    decode_binary_frame,
    decode_metadata,
    derive_axis_timing,
)


def _frame(channel: int, values: list[float] | None = None, *, prefix: bytes = b"\xe5\xd2\x00") -> bytes:
    if values is None:
        values = [float(index) / 10.0 for index in range(FIELD_SAMPLE_COUNT)]
    return prefix + bytes([channel]) + struct.pack(f"<{len(values)}f", *values)


def _metadata(phase: int, *, ms: float = 35.6) -> str:
    return json.dumps(
        {
            "type": "scope",
            "phase": phase,
            "connected": 1,
            "vrms": 232.11 + phase,
            "irms": 10.21 + phase,
            "freq": 50.01,
            "pf": -0.0125 + phase * 0.01,
            "ms": ms,
        }
    )


def test_binary_decoder_preserves_qualified_little_endian_float32_samples() -> None:
    values = [13.2386551, -13.4510374] + [float(index) / 100.0 for index in range(230)]
    payload = _frame(0, values)
    frame = decode_binary_frame(payload)

    expected = struct.unpack(f"<{FIELD_SAMPLE_COUNT}f", payload[4:])
    assert frame.channel == 0
    assert frame.channel_name == "Phase A current"
    assert frame.header_hex == "e5d20000"
    assert frame.header_prefix_hex == "e5d200"
    assert frame.frame_bytes == FIELD_FRAME_BYTES
    assert frame.sample_count == FIELD_SAMPLE_COUNT
    assert frame.samples == expected
    assert frame.nonfinite_count == 0


def test_binary_decoder_enforces_field_qualified_structure_without_clamping() -> None:
    with pytest.raises(ValueError, match="932 bytes"):
        decode_binary_frame(_frame(0, [1.0] * 231))
    with pytest.raises(ValueError, match="channel"):
        decode_binary_frame(_frame(6))



@pytest.mark.parametrize("prefix_hex", ["e5d200", "810400", "e90f00"])
def test_binary_decoder_accepts_observed_device_prefix_variants_as_diagnostic_evidence(prefix_hex: str) -> None:
    prefix = bytes.fromhex(prefix_hex)
    frame = decode_binary_frame(_frame(4, prefix=prefix))
    assert frame.channel == 4
    assert frame.header_prefix_hex == prefix_hex
    assert frame.header_hex == f"{prefix_hex}04"
    assert frame.frame_bytes == FIELD_FRAME_BYTES
    assert frame.sample_count == FIELD_SAMPLE_COUNT


def test_capture_serialization_exposes_observed_header_prefixes_without_assigning_validity() -> None:
    prefixes = ["e5d200", "810400", "e90f00", "e5d200", "810400", "e90f00"]
    frames = {
        channel: decode_binary_frame(_frame(channel, prefix=bytes.fromhex(prefixes[channel])))
        for channel in range(6)
    }
    metadata = {phase: decode_metadata(_metadata(phase)) for phase in range(3)}
    capture = build_capture(
        sequence=9,
        received_utc="2026-08-28T10:00:00+00:00",
        channels=frames,
        metadata=metadata,
        channel_order=(0, 1, 2, 3, 4, 5),
        metadata_order=(0, 1, 2),
    )
    payload = capture.as_dict()
    assert payload["observed_header_prefixes"] == ["810400", "e5d200", "e90f00"]


def test_binary_decoder_reports_nonfinite_samples_without_replacing_them() -> None:
    values = [0.0] * FIELD_SAMPLE_COUNT
    values[10] = math.nan
    values[20] = math.inf
    frame = decode_binary_frame(_frame(1, values))
    assert frame.nonfinite_count == 2
    assert math.isnan(frame.samples[10])
    assert math.isinf(frame.samples[20])


def test_metadata_decoder_preserves_raw_scope_values_and_rejects_wrong_shape() -> None:
    item = decode_metadata(_metadata(2))
    assert item is not None
    assert item.phase == 2
    assert item.connected == 1
    assert item.vrms == 234.11
    assert item.irms == 12.21
    assert item.frequency == 50.01
    assert item.pf == pytest.approx(0.0075)
    assert item.capture_ms == 35.6
    assert item.raw["type"] == "scope"

    assert decode_metadata('{"type":"other","phase":0}') is None
    with pytest.raises(ValueError, match="phase"):
        decode_metadata(_metadata(3))
    bad = json.loads(_metadata(0))
    del bad["ms"]
    with pytest.raises(ValueError, match="ms"):
        decode_metadata(json.dumps(bad))


def test_axis_timing_is_derived_from_capture_axis_and_sample_count_only() -> None:
    timing = derive_axis_timing(sample_count=232, capture_ms=35.6)
    assert timing.sample_interval_ms == pytest.approx(35.6 / 231.0, abs=1e-15)
    assert timing.sample_rate_hz == pytest.approx(231.0 / 0.0356, abs=1e-12)


def test_build_capture_requires_all_six_channels_and_three_metadata_phases() -> None:
    frames = {channel: decode_binary_frame(_frame(channel)) for channel in range(6)}
    metadata = {phase: decode_metadata(_metadata(phase)) for phase in range(3)}
    capture = build_capture(
        sequence=7,
        received_utc="2026-08-28T09:30:00+00:00",
        channels=frames,
        metadata=metadata,
        channel_order=(0, 1, 2, 3, 4, 5),
        metadata_order=(0, 1, 2),
    )
    assert capture.sequence == 7
    assert capture.received_utc == "2026-08-28T09:30:00+00:00"
    assert capture.capture_ms == 35.6
    assert capture.sample_count == 232
    assert capture.sample_rate_hz == pytest.approx(6488.76404494382)
    assert capture.channels[5].channel_name == "Phase C voltage"

    incomplete = dict(frames)
    incomplete.pop(5)
    with pytest.raises(ValueError, match="channels 0..5"):
        build_capture(
            sequence=1,
            received_utc="x",
            channels=incomplete,
            metadata=metadata,
            channel_order=(0, 1, 2, 3, 4),
            metadata_order=(0, 1, 2),
        )


def test_build_capture_rejects_duplicate_order_or_mismatched_capture_duration() -> None:
    frames = {channel: decode_binary_frame(_frame(channel)) for channel in range(6)}
    metadata = {phase: decode_metadata(_metadata(phase)) for phase in range(3)}
    with pytest.raises(ValueError, match="channel order"):
        build_capture(
            sequence=1,
            received_utc="x",
            channels=frames,
            metadata=metadata,
            channel_order=(0, 1, 2, 3, 4, 4),
            metadata_order=(0, 1, 2),
        )

    metadata[2] = decode_metadata(_metadata(2, ms=35.7))
    with pytest.raises(ValueError, match="capture duration"):
        build_capture(
            sequence=1,
            received_utc="x",
            channels=frames,
            metadata=metadata,
            channel_order=(0, 1, 2, 3, 4, 5),
            metadata_order=(0, 1, 2),
        )


def test_build_capture_rejects_nonfinite_waveform_samples_fail_closed() -> None:
    values = [0.0] * FIELD_SAMPLE_COUNT
    values[17] = math.nan
    frames = {channel: decode_binary_frame(_frame(channel)) for channel in range(6)}
    frames[2] = decode_binary_frame(_frame(2, values))
    metadata = {phase: decode_metadata(_metadata(phase)) for phase in range(3)}

    with pytest.raises(ValueError, match="non-finite"):
        build_capture(
            sequence=1,
            received_utc="x",
            channels=frames,
            metadata=metadata,
            channel_order=(0, 1, 2, 3, 4, 5),
            metadata_order=(0, 1, 2),
        )
