from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import threading

from .model import CtConfigurationEvidence, ModbusDeviceEvidence


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


class ModbusDeviceEvidenceService:
    """Read and retain non-canonical Modbus device evidence in memory."""

    def __init__(
        self,
        reader,
        *,
        coordinator,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._reader = reader
        self._coordinator = coordinator
        self._clock = clock
        self._lock = threading.RLock()
        self._evidence: dict[str, ModbusDeviceEvidence] = {}

    async def read(self, device) -> ModbusDeviceEvidence:
        request = self._coordinator.request_modbus_device_evidence(
            device.id,
            self._reader,
        )
        values = await asyncio.wrap_future(request)
        evidence = ModbusDeviceEvidence(
            device_id=device.id,
            observed_utc=self._clock(),
            values=values,
        )
        with self._lock:
            self._evidence[device.id] = evidence
        return evidence

    def get(self, device_id: str) -> ModbusDeviceEvidence | None:
        with self._lock:
            return self._evidence.get(device_id)
