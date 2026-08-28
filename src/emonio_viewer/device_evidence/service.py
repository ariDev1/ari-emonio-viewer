from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import threading

from .model import CtConfigurationEvidence


class CtConfigurationService:
    """Read and retain CT evidence in memory. Credentials are not retained."""

    def __init__(
        self,
        reader,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._reader = reader
        self._clock = clock
        self._lock = threading.RLock()
        self._evidence: dict[str, CtConfigurationEvidence] = {}

    async def read(self, device_id: str, host: str, password: str) -> CtConfigurationEvidence:
        values = await asyncio.to_thread(self._reader.read, host, password)
        evidence = CtConfigurationEvidence(
            device_id=device_id,
            observed_utc=self._clock(),
            values=values,
        )
        with self._lock:
            self._evidence[device_id] = evidence
        return evidence

    def get(self, device_id: str) -> CtConfigurationEvidence | None:
        with self._lock:
            return self._evidence.get(device_id)
