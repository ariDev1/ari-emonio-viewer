from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ScopeSessionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    HOLD = "HOLD"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ScopeWaveformFrame:
    channel: int
    channel_name: str
    header_hex: str
    header_prefix_hex: str
    frame_bytes: int
    payload_sha256: str
    samples: tuple[float, ...]
    nonfinite_count: int

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "channel_name": self.channel_name,
            "header_hex": self.header_hex,
            "header_prefix_hex": self.header_prefix_hex,
            "frame_bytes": self.frame_bytes,
            "sample_count": self.sample_count,
            "payload_sha256": self.payload_sha256,
            "nonfinite_count": self.nonfinite_count,
            "samples": list(self.samples),
        }


@dataclass(frozen=True, slots=True)
class ScopeMetadata:
    phase: int
    connected: int
    vrms: float
    irms: float
    frequency: float
    pf: float
    capture_ms: float
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "connected": self.connected,
            "vrms": self.vrms,
            "irms": self.irms,
            "frequency": self.frequency,
            "pf": self.pf,
            "capture_ms": self.capture_ms,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True, slots=True)
class ScopeAxisTiming:
    sample_interval_ms: float
    sample_rate_hz: float


@dataclass(frozen=True, slots=True)
class ScopeCapture:
    sequence: int
    received_utc: str
    channels: dict[int, ScopeWaveformFrame]
    metadata: dict[int, ScopeMetadata]
    channel_order: tuple[int, ...]
    metadata_order: tuple[int, ...]
    capture_ms: float
    sample_count: int
    sample_interval_ms: float
    sample_rate_hz: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "received_utc": self.received_utc,
            "source": "EMONIO_WEBSOCKET_SCOPE",
            "capture_ms": self.capture_ms,
            "sample_count": self.sample_count,
            "sample_interval_ms": self.sample_interval_ms,
            "sample_rate_hz": self.sample_rate_hz,
            "sample_rate_basis": "DERIVED_FROM_CAPTURE_AXIS_AND_SAMPLE_COUNT",
            "channel_order": list(self.channel_order),
            "metadata_order": list(self.metadata_order),
            "observed_header_prefixes": sorted({frame.header_prefix_hex for frame in self.channels.values()}),
            "channels": {str(key): value.as_dict() for key, value in sorted(self.channels.items())},
            "metadata": {str(key): value.as_dict() for key, value in sorted(self.metadata.items())},
        }


@dataclass(frozen=True, slots=True)
class ScopeStatus:
    device_id: str
    state: ScopeSessionState
    error: str | None
    capture: ScopeCapture | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "state": self.state.value,
            "source": "EMONIO_WEBSOCKET_SCOPE",
            "error": self.error,
            "capture": None if self.capture is None else self.capture.as_dict(),
        }
