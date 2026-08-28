import csv
import math
from pathlib import Path

from emonio_viewer.measurement.model import MeasurementSample


MEASUREMENT_FIELDS = [
    "record_utc",
    "cycle_id",
    "sample_age_ms",
    "quality",
    *[
        f"{prefix}_{field}"
        for prefix in ("A", "B", "C", "T")
        for field in ("vrms", "irms", "p", "q", "s", "pf", "freq", "kwh", "quadrant")
    ],
    "derived_sum_p",
    "derived_sum_q",
    "derived_sum_s",
    "delta_p",
    "delta_q",
    "delta_s",
]
EVENT_FIELDS = ["utc", "event", "severity", "cycle_id", "detail"]
OUTPUT_DECIMAL_PLACES = 4


def _format_numeric(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("cannot serialize non-finite measurement value")
    return f"{value:.{OUTPUT_DECIMAL_PLACES}f}"


class CsvWriters:
    def __init__(self, session_dir: Path) -> None:
        self._measurements = (session_dir / "measurements.csv").open(
            "x",
            newline="",
            encoding="utf-8",
        )
        self._events = (session_dir / "events.csv").open(
            "x",
            newline="",
            encoding="utf-8",
        )
        self.measurement_writer = csv.DictWriter(self._measurements, fieldnames=MEASUREMENT_FIELDS)
        self.event_writer = csv.DictWriter(self._events, fieldnames=EVENT_FIELDS)
        self.measurement_writer.writeheader()
        self._measurements.flush()
        self.event_writer.writeheader()
        self._events.flush()

    def write_measurement(self, row: dict[str, str]) -> None:
        self.measurement_writer.writerow(row)
        self._measurements.flush()

    def write_event(self, row: dict[str, str]) -> None:
        self.event_writer.writerow(row)
        self._events.flush()

    def close(self) -> None:
        self._measurements.close()
        self._events.close()


def sample_to_csv_row(
    sample: MeasurementSample,
    record_utc: str,
    sample_age_ms: float,
) -> dict[str, str]:
    row: dict[str, str] = {
        "record_utc": record_utc,
        "cycle_id": str(sample.identity.cycle_id),
        "sample_age_ms": _format_numeric(sample_age_ms),
        "quality": sample.quality.value,
    }
    for prefix, block in (
        ("A", sample.phase_a),
        ("B", sample.phase_b),
        ("C", sample.phase_c),
        ("T", sample.total),
    ):
        measurement = block.measurement
        values = {
            "vrms": measurement.vrms,
            "irms": measurement.irms,
            "p": measurement.p,
            "q": measurement.q,
            "s": measurement.s,
            "pf": measurement.pf,
            "freq": measurement.frequency,
            "kwh": measurement.energy,
        }
        for field, value in values.items():
            row[f"{prefix}_{field}"] = _format_numeric(value)
        row[f"{prefix}_quadrant"] = block.quadrant.value

    row.update(
        {
            "derived_sum_p": _format_numeric(sample.derived.sum_p),
            "derived_sum_q": _format_numeric(sample.derived.sum_q),
            "derived_sum_s": _format_numeric(sample.derived.sum_s),
            "delta_p": _format_numeric(sample.derived.delta_p),
            "delta_q": _format_numeric(sample.derived.delta_q),
            "delta_s": _format_numeric(sample.derived.delta_s),
        }
    )
    return row
