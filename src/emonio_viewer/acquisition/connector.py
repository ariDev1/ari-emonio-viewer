from __future__ import annotations

import asyncio
from dataclasses import dataclass

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.device_evidence.firmware import FirmwareProbeError, probe_firmware_version
from emonio_viewer.modbus.transport import ReadOnlyModbusClient

from .coordinator import AcquisitionCoordinator
from .target import TargetInputError, parse_target
from .worker import AcquisitionCycleError, AcquisitionWorker


class TargetConnectionError(RuntimeError):
    """Raised when a target does not produce one complete valid Modbus cycle."""


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    device: DeviceConfig
    already_connected: bool


class DeviceConnector:
    """Qualify an operator-supplied target before adding it to live acquisition."""

    def __init__(
        self,
        coordinator: AcquisitionCoordinator,
        recording,
        *,
        registry=None,
        port: int = 502,
        unit_id: int = 1,
        poll_interval_s: float = 2.0,
        timeout_s: float = 2.0,
    ) -> None:
        self._coordinator = coordinator
        self._recording = recording
        self._registry = registry
        self._port = port
        self._unit_id = unit_id
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s

    def device_configs(self) -> tuple[DeviceConfig, ...]:
        return self._coordinator.device_configs()

    def get_device_config(self, device_id: str) -> DeviceConfig:
        return self._coordinator.get_device_config(device_id)

    def _existing(self, name: str, host: str) -> DeviceConfig | None:
        for device in self.device_configs():
            if device.host == host or device.name == name:
                return device
        return None

    def _unique_id(self, base: str) -> str:
        existing = {device.id for device in self.device_configs()}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    async def _probe_firmware_version(self, host: str) -> str:
        """Best-effort read-only firmware discovery; never fails the connect."""
        try:
            return await asyncio.to_thread(probe_firmware_version, host)
        except FirmwareProbeError:
            return "unknown"
        except Exception:
            return "unknown"

    def note_device_firmware(self, device_id: str, firmware_version: str) -> None:
        """Adopt device-observed firmware evidence for live display/provenance.

        Best-effort sink for evidence services (SCOPE, Telnet info): upgrades
        "unknown" values in the coordinator and the remembered registry.
        Never raises.
        """
        try:
            changed = self._coordinator.update_device_firmware(device_id, firmware_version)
        except Exception:
            return
        if not changed or self._registry is None:
            return
        try:
            self._registry.update_firmware(device_id, firmware_version)
        except Exception:
            pass

    async def connect(self, target_text: str) -> ConnectionResult:
        try:
            target = parse_target(target_text)
        except TargetInputError:
            raise

        existing = self._existing(target.name, target.host)
        if existing is not None:
            return ConnectionResult(existing, True)

        device = DeviceConfig(
            id=self._unique_id(target.name),
            name=target.name,
            host=target.host,
            port=self._port,
            unit_id=self._unit_id,
            poll_interval_s=self._poll_interval_s,
            timeout_s=self._timeout_s,
            enabled=True,
            firmware_version=await self._probe_firmware_version(target.host),
        )
        client = ReadOnlyModbusClient(
            device.host,
            device.port,
            device.unit_id,
            device.timeout_s,
        )
        worker = AcquisitionWorker(device, client)
        try:
            sample = await asyncio.to_thread(worker.run_cycle, 1, 0.0)
            connections_opened = client.connections_opened
        except AcquisitionCycleError as exc:
            raise TargetConnectionError(str(exc)) from exc
        except OSError as exc:
            raise TargetConnectionError(str(exc)) from exc
        finally:
            client.close()

        self._recording.register_device(device)
        self._coordinator.add_device(
            device,
            initial_sample=sample,
            initial_connections_opened=connections_opened,
        )
        if self._registry is not None:
            self._registry.remember(device)
        return ConnectionResult(device, False)
