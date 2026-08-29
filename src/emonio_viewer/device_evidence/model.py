from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CtConfigurationValues:
    """Raw integer values returned by the Emonio `conf ct_*` commands."""

    ct_type: int
    ct_voltage: int
    ct_range: int
    ct_invert: int
    ct_didt: int

    def as_dict(self) -> dict[str, int]:
        return {
            "ct_type": self.ct_type,
            "ct_voltage": self.ct_voltage,
            "ct_range": self.ct_range,
            "ct_invert": self.ct_invert,
            "ct_didt": self.ct_didt,
        }


@dataclass(frozen=True, slots=True)
class CtConfigurationEvidence:
    """Observed Emonio CT configuration without physical-orientation claims."""

    device_id: str
    observed_utc: datetime
    values: CtConfigurationValues

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "observed_utc": self.observed_utc.isoformat(),
            "source": "EMONIO_TELNET_CONF",
            "transport": "TELNET",
            "interpretation": "RAW_DEVICE_CONFIGURATION",
            "physical_orientation_status": "NOT_VERIFIED",
            "values": self.values.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class EnergyFlowEvidence:
    """Documented Emonio cumulative imported and exported energy values."""

    energy_in: float
    energy_out: float

    def as_dict(self) -> dict[str, float]:
        return {"kwh_in": self.energy_in, "kwh_out": self.energy_out}


@dataclass(frozen=True, slots=True)
class ModbusEvidenceReadDiagnostic:
    """Exact result of one non-canonical read-only Modbus evidence probe."""

    key: str
    function_code: int
    address: int
    count: int
    status: str
    elapsed_ms: float
    error_type: str | None = None
    error_detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "function_code": self.function_code,
            "address": self.address,
            "count": self.count,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "error_type": self.error_type,
            "error_detail": self.error_detail,
        }


@dataclass(frozen=True, slots=True)
class ModbusDeviceEvidenceValues:
    """Read-only Emonio values outside the canonical measurement sample."""

    energy: dict[str, EnergyFlowEvidence | None]
    connected: dict[str, bool | None]
    error_raw: int | None
    warning_raw: int | None
    error_flags: tuple[str, ...] | None
    warning_flags: tuple[str, ...] | None
    read_diagnostics: tuple[ModbusEvidenceReadDiagnostic, ...]

    @property
    def read_status(self) -> str:
        statuses = tuple(item.status for item in self.read_diagnostics)
        if statuses and all(status == "OK" for status in statuses):
            return "OBSERVED"
        if any(status == "OK" for status in statuses):
            return "PARTIAL"
        return "FAILED"

    def as_dict(self) -> dict:
        return {
            "energy": {
                phase: value.as_dict() if value is not None else None
                for phase, value in self.energy.items()
            },
            "connected": dict(self.connected),
            "error_raw": self.error_raw,
            "warning_raw": self.warning_raw,
            "error_flags": list(self.error_flags) if self.error_flags is not None else None,
            "warning_flags": list(self.warning_flags) if self.warning_flags is not None else None,
            "read_diagnostics": [item.as_dict() for item in self.read_diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ModbusDeviceEvidence:
    """Observed read-only Emonio Modbus values kept separate from canonical samples."""

    device_id: str
    observed_utc: datetime
    values: ModbusDeviceEvidenceValues

    @property
    def read_status(self) -> str:
        return self.values.read_status

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "observed_utc": self.observed_utc.isoformat(),
            "source": "EMONIO_MODBUS_TCP_DEVICE_EVIDENCE",
            "transport": "MODBUS_TCP",
            "interpretation": "DOCUMENTED_DEVICE_VALUES",
            "read_status": self.read_status,
            "values": self.values.as_dict(),
        }
