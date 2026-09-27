from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import threading

from .model import CtConfigurationEvidence, DeviceFirmwareEvidence, ModbusDeviceEvidence


class CtConfigurationService:
    """Read and retain CT evidence in memory. Credentials are not retained."""

    def __init__(
        self,
        reader,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        firmware_sink: Callable[[str, str], None] | None = None,
    ) -> None:
        self._reader = reader
        self._clock = clock
        if firmware_sink is not None and not callable(firmware_sink):
            raise ValueError("firmware_sink must be callable")
        self._firmware_sink = firmware_sink
        self._lock = threading.RLock()
        self._evidence: dict[str, CtConfigurationEvidence] = {}
        self._firmware: dict[str, DeviceFirmwareEvidence] = {}

    async def read(self, device_id: str, host: str, password: str) -> CtConfigurationEvidence:
        read_with_firmware = getattr(self._reader, "read_with_firmware", None)
        if callable(read_with_firmware):
            values, firmware, detail = await asyncio.to_thread(
                read_with_firmware, host, password
            )
        else:
            values = await asyncio.to_thread(self._reader.read, host, password)
            firmware, detail = None, "READER_HAS_NO_FIRMWARE_PATH"
        evidence = CtConfigurationEvidence(
            device_id=device_id,
            observed_utc=self._clock(),
            values=values,
        )
        with self._lock:
            self._evidence[device_id] = evidence
            self._firmware[device_id] = DeviceFirmwareEvidence(
                device_id=device_id,
                observed_utc=evidence.observed_utc,
                firmware=firmware,
                detail=detail,
            )
        if firmware is not None and self._firmware_sink is not None:
            try:
                self._firmware_sink(device_id, firmware)
            except Exception:
                pass
        return evidence

    def get(self, device_id: str) -> CtConfigurationEvidence | None:
        with self._lock:
            return self._evidence.get(device_id)

    def get_firmware(self, device_id: str) -> DeviceFirmwareEvidence | None:
        with self._lock:
            return self._firmware.get(device_id)


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
