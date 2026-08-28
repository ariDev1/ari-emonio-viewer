from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import struct
from typing import Mapping

from .model import ScopeAxisTiming, ScopeCapture, ScopeMetadata, ScopeWaveformFrame

FIELD_SAMPLE_COUNT = 232
FIELD_FRAME_BYTES = 932
SCOPE_REQUEST_INTERVAL_S = 1.009
SCOPE_COMMAND = "scope"
SCOPE_CHANNEL_NAMES = {
    0: "Phase A current",
    1: "Phase A voltage",
    2: "Phase B current",
    3: "Phase B voltage",
    4: "Phase C current",
    5: "Phase C voltage",
}


def decode_binary_frame(payload: bytes) -> ScopeWaveformFrame:
    if len(payload) != FIELD_FRAME_BYTES:
        raise ValueError(f"scope frame must contain exactly {FIELD_FRAME_BYTES} bytes")
    prefix = payload[:3].hex()
    channel = payload[3]
    if channel not in SCOPE_CHANNEL_NAMES:
        raise ValueError(f"unexpected scope channel {channel}")
    samples = struct.unpack(f"<{FIELD_SAMPLE_COUNT}f", payload[4:])
    nonfinite_count = sum(1 for value in samples if not math.isfinite(value))
    return ScopeWaveformFrame(
        channel=channel,
        channel_name=SCOPE_CHANNEL_NAMES[channel],
        header_hex=payload[:4].hex(),
        header_prefix_hex=prefix,
        frame_bytes=len(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        samples=tuple(samples),
        nonfinite_count=nonfinite_count,
    )


def _required_number(raw: dict, key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"scope metadata {key} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"scope metadata {key} must be finite")
    return result


def decode_metadata(text: str) -> ScopeMetadata | None:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("type") != "scope":
        return None
    phase = raw.get("phase")
    if isinstance(phase, bool) or not isinstance(phase, int) or phase not in {0, 1, 2}:
        raise ValueError("scope metadata phase must be 0, 1, or 2")
    connected = raw.get("connected")
    if isinstance(connected, bool) or not isinstance(connected, int):
        raise ValueError("scope metadata connected must be an integer")
    capture_ms = _required_number(raw, "ms")
    if capture_ms <= 0:
        raise ValueError("scope metadata ms must be greater than zero")
    return ScopeMetadata(
        phase=phase,
        connected=connected,
        vrms=_required_number(raw, "vrms"),
        irms=_required_number(raw, "irms"),
        frequency=_required_number(raw, "freq"),
        pf=_required_number(raw, "pf"),
        capture_ms=capture_ms,
        raw=dict(raw),
    )


def derive_axis_timing(*, sample_count: int, capture_ms: float) -> ScopeAxisTiming:
    if sample_count < 2:
        raise ValueError("sample_count must be at least two")
    if not math.isfinite(capture_ms) or capture_ms <= 0:
        raise ValueError("capture_ms must be finite and greater than zero")
    interval_ms = capture_ms / (sample_count - 1)
    return ScopeAxisTiming(
        sample_interval_ms=interval_ms,
        sample_rate_hz=(sample_count - 1) / (capture_ms / 1000.0),
    )


def build_capture(
    *,
    sequence: int,
    received_utc: str | None,
    channels: Mapping[int, ScopeWaveformFrame],
    metadata: Mapping[int, ScopeMetadata],
    channel_order: tuple[int, ...],
    metadata_order: tuple[int, ...],
) -> ScopeCapture:
    if set(channels) != set(range(6)):
        raise ValueError("scope capture requires channels 0..5")
    if set(metadata) != set(range(3)):
        raise ValueError("scope capture requires metadata phases 0..2")
    if channel_order != (0, 1, 2, 3, 4, 5):
        raise ValueError("scope channel order must be exactly 0,1,2,3,4,5")
    if metadata_order != (0, 1, 2):
        raise ValueError("scope metadata order must be exactly 0,1,2")
    if any(frame.sample_count != FIELD_SAMPLE_COUNT for frame in channels.values()):
        raise ValueError(f"scope capture requires {FIELD_SAMPLE_COUNT} samples per channel")
    if any(frame.nonfinite_count != 0 for frame in channels.values()):
        raise ValueError("scope capture contains non-finite waveform samples")
    capture_values = {item.capture_ms for item in metadata.values()}
    if len(capture_values) != 1:
        raise ValueError("scope metadata capture duration must match across all phases")
    capture_ms = next(iter(capture_values))
    timing = derive_axis_timing(sample_count=FIELD_SAMPLE_COUNT, capture_ms=capture_ms)
    if received_utc is None:
        received_utc = datetime.now(timezone.utc).isoformat()
    return ScopeCapture(
        sequence=sequence,
        received_utc=received_utc,
        channels=dict(channels),
        metadata=dict(metadata),
        channel_order=channel_order,
        metadata_order=metadata_order,
        capture_ms=capture_ms,
        sample_count=FIELD_SAMPLE_COUNT,
        sample_interval_ms=timing.sample_interval_ms,
        sample_rate_hz=timing.sample_rate_hz,
    )
