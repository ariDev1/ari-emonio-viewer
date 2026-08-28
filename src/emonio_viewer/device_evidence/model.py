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
