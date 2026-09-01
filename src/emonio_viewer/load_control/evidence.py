from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class EvidenceWriteError(OSError):
    """Raised when required load-control evidence cannot be appended."""


class ControlEvidenceWriter:
    """Append-only JSONL evidence for load-control facts and decisions."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.healthy = True
        self.last_error: str | None = None

    def append(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict) or not isinstance(event.get("event"), str) or not event["event"]:
            raise ValueError("evidence event must contain non-empty event text")
        try:
            encoded = json.dumps(
                event,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, TypeError, ValueError) as exc:
            self.healthy = False
            self.last_error = str(exc) or type(exc).__name__
            raise EvidenceWriteError(self.last_error) from exc
        self.healthy = True
        self.last_error = None

    def recent(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be integer > 0")
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            result: list[dict[str, Any]] = []
            for line in lines[-limit:]:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("evidence line must be an object")
                result.append(raw)
            return tuple(result)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            self.healthy = False
            self.last_error = str(exc) or type(exc).__name__
            raise EvidenceWriteError(self.last_error) from exc
