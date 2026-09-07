from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
from typing import Callable


_EVENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    sequence: int
    utc: str
    event: str
    line: str


def _format_utc(moment: datetime) -> str:
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("diagnostic log clock must return timezone-aware datetime")
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_value(value) -> str:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("diagnostic field float must be finite")
        return json.dumps(value, separators=(",", ":"))
    raise ValueError("diagnostic field values must be strings, finite numbers, booleans, or null")


class LoadControlDiagnosticLog:
    """Bounded in-memory diagnostic output for real actuator network qualification."""

    def __init__(
        self,
        *,
        max_events: int = 200,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events <= 0:
            raise ValueError("max_events must be a positive integer")
        self._events: deque[DiagnosticEvent] = deque(maxlen=max_events)
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._latest_sequence = 0

    @property
    def latest_sequence(self) -> int:
        return self._latest_sequence

    def append(self, event: str, **fields) -> DiagnosticEvent:
        if not isinstance(event, str) or not _EVENT_NAME.fullmatch(event):
            raise ValueError("event must be an uppercase diagnostic event name")
        for name in fields:
            if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
                raise ValueError("diagnostic field names must use lower snake case")

        self._latest_sequence += 1
        utc = _format_utc(self._utc_now())
        suffix = "".join(f" {name}={_format_value(value)}" for name, value in fields.items())
        item = DiagnosticEvent(
            sequence=self._latest_sequence,
            utc=utc,
            event=event,
            line=f"{utc}  {event}{suffix}",
        )
        self._events.append(item)
        return item

    def recent(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[DiagnosticEvent, ...]:
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")

        values = tuple(item for item in self._events if item.sequence > after_sequence)
        if limit is not None:
            values = values[-limit:]
        return values
