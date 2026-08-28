from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .quadrant import ActiveFlowState, QuadrantState


class SampleQuality(str, Enum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class PhaseMeasurement:
    vrms: float
    irms: float
    p: float
    q: float
    s: float
    frequency: float
    energy: float
    pf: float


@dataclass(frozen=True, slots=True)
class RawBlockEvidence:
    base_register: int
    words: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BlockState:
    measurement: PhaseMeasurement
    quadrant: QuadrantState
    flow: ActiveFlowState
    acquired_utc: datetime
    raw: RawBlockEvidence


@dataclass(frozen=True, slots=True)
class SampleTiming:
    cycle_started_utc: datetime
    cycle_finished_utc: datetime
    cycle_started_monotonic_ns: int
    cycle_finished_monotonic_ns: int
    cycle_span_ms: float


@dataclass(frozen=True, slots=True)
class AcquisitionMetadata:
    schedule_lag_ms: float


@dataclass(frozen=True, slots=True)
class MeasurementIdentity:
    schema_version: int
    device_id: str
    device_name: str
    device_ip: str
    firmware_version: str
    transport: str
    cycle_id: int


@dataclass(frozen=True, slots=True)
class DerivedTotals:
    sum_p: float
    sum_q: float
    sum_s: float
    delta_p: float
    delta_q: float
    delta_s: float


@dataclass(frozen=True, slots=True)
class MeasurementSample:
    identity: MeasurementIdentity
    timing: SampleTiming
    acquisition: AcquisitionMetadata
    phase_a: BlockState
    phase_b: BlockState
    phase_c: BlockState
    total: BlockState
    quality: SampleQuality
    warnings: tuple[str, ...]
    derived: DerivedTotals
