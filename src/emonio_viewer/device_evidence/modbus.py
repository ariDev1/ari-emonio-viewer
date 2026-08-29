from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

from emonio_viewer.modbus.decoder import decode_cdab_float
from emonio_viewer.modbus.protocol import ModbusProtocolError
from emonio_viewer.modbus.transport import ReadOnlyModbusClient

from .model import (
    EnergyFlowEvidence,
    ModbusDeviceEvidenceValues,
    ModbusEvidenceReadDiagnostic,
)


ENERGY_FLOW_BASES = {"A": 40, "B": 140, "C": 240, "TOTAL": 340}
CONNECTED_INPUT_BASE = 0
CONNECTED_INPUT_COUNT = 3
STATUS_REGISTER_BASE = 1000
STATUS_REGISTER_COUNT = 2

ERROR_FLAGS: dict[int, str] = {
    0: "ERROR_UNKNOWN",
    1: "RESERVED",
    2: "FS_FULL",
    3: "FS_CORRUPT",
    4: "RTC_DEFECT",
    5: "RTC_BATTERY",
    6: "EEPROM_DEFECT",
    7: "WIFI_AUTH_FAILED",
    8: "MODEL_MISMATCH",
    9: "TELEMETRY_BUFFER",
    10: "TELEMETRY_LICENSE",
    11: "STORAGE_ANOMALY",
    12: "SENSOR_COMMUNICATION",
    13: "SENSOR_CALIBRATION",
    14: "SENSOR_DATA_INVALID",
}

WARNING_FLAGS: dict[int, str] = {
    0: "UNKNOWN",
    1: "FS_LOW",
    2: "TIME_NOT_SET",
    3: "WIFI_SSID_UNAVAILABLE",
    4: "TELEMETRY_DISCONNECTED",
    5: "TELEMETRY_EXPORT",
    6: "TELEMETRY_BUFFER",
    7: "TELEMETRY_LICENSE",
}


class ModbusDeviceEvidenceReadError(RuntimeError):
    """Reserved for unexpected device-evidence service failures."""


def decode_energy_flow_registers(words: Sequence[int]) -> tuple[float, float]:
    if len(words) != 4:
        raise ValueError(f"expected 4 energy-flow registers, got {len(words)}")
    energy_in = decode_cdab_float(words[0], words[1])
    energy_out = decode_cdab_float(words[2], words[3])
    if not math.isfinite(energy_in) or not math.isfinite(energy_out):
        raise ValueError("non-finite KWH IN/OUT device evidence")
    return energy_in, energy_out


def decode_status_flags(raw: int, mapping: Mapping[int, str]) -> tuple[str, ...]:
    if not 0 <= raw <= 0xFFFF:
        raise ValueError("status register must be an unsigned 16-bit integer")
    return tuple(name for bit, name in mapping.items() if raw & (1 << bit))


_T = TypeVar("_T")
_READ_ERRORS = (OSError, ConnectionError, ModbusProtocolError, ValueError)
_TRANSPORT_ERRORS = (OSError, ConnectionError)


class ModbusDeviceEvidenceReader:
    """Read auxiliary evidence through the acquisition worker's Modbus client."""

    def __init__(self, *, timer: Callable[[], float] = time.perf_counter) -> None:
        self._timer = timer

    def _probe(
        self,
        client: ReadOnlyModbusClient,
        *,
        key: str,
        function_code: int,
        address: int,
        count: int,
        operation: Callable[[ReadOnlyModbusClient], _T],
    ) -> tuple[_T | None, ModbusEvidenceReadDiagnostic, bool]:
        started = self._timer()
        try:
            value = operation(client)
        except _READ_ERRORS as exc:
            elapsed_ms = max(0.0, (self._timer() - started) * 1000.0)
            transport_failed = isinstance(exc, _TRANSPORT_ERRORS)
            if transport_failed:
                client.close()
            return (
                None,
                ModbusEvidenceReadDiagnostic(
                    key=key,
                    function_code=function_code,
                    address=address,
                    count=count,
                    status="ERROR",
                    elapsed_ms=elapsed_ms,
                    error_type=type(exc).__name__,
                    error_detail=str(exc) or type(exc).__name__,
                ),
                transport_failed,
            )

        elapsed_ms = max(0.0, (self._timer() - started) * 1000.0)
        return (
            value,
            ModbusEvidenceReadDiagnostic(
                key=key,
                function_code=function_code,
                address=address,
                count=count,
                status="OK",
                elapsed_ms=elapsed_ms,
            ),
            False,
        )

    @staticmethod
    def _skipped_diagnostic(
        *,
        key: str,
        function_code: int,
        address: int,
        count: int,
        failed_key: str,
    ) -> ModbusEvidenceReadDiagnostic:
        return ModbusEvidenceReadDiagnostic(
            key=key,
            function_code=function_code,
            address=address,
            count=count,
            status="SKIPPED",
            elapsed_ms=0.0,
            error_type="EvidenceSequenceAborted",
            error_detail=f"not attempted after transport failure in {failed_key}",
        )

    def read(self, client: ReadOnlyModbusClient) -> ModbusDeviceEvidenceValues:
        diagnostics: list[ModbusEvidenceReadDiagnostic] = []
        energy: dict[str, EnergyFlowEvidence | None] = {
            phase: None for phase in ENERGY_FLOW_BASES
        }
        failed_transport_key: str | None = None

        for phase, base in ENERGY_FLOW_BASES.items():
            key = f"ENERGY_{phase}"
            if failed_transport_key is not None:
                diagnostics.append(
                    self._skipped_diagnostic(
                        key=key,
                        function_code=0x03,
                        address=base,
                        count=4,
                        failed_key=failed_transport_key,
                    )
                )
                continue

            result, diagnostic, transport_failed = self._probe(
                client,
                key=key,
                function_code=0x03,
                address=base,
                count=4,
                operation=lambda active_client, base=base: EnergyFlowEvidence(
                    *decode_energy_flow_registers(
                        active_client.read_holding_registers(base, 4)
                    )
                ),
            )
            energy[phase] = result
            diagnostics.append(diagnostic)
            if transport_failed:
                failed_transport_key = key

        if failed_transport_key is not None:
            connected_result = None
            diagnostics.append(
                self._skipped_diagnostic(
                    key="CONNECTED_ABC",
                    function_code=0x02,
                    address=CONNECTED_INPUT_BASE,
                    count=CONNECTED_INPUT_COUNT,
                    failed_key=failed_transport_key,
                )
            )
        else:
            connected_result, diagnostic, transport_failed = self._probe(
                client,
                key="CONNECTED_ABC",
                function_code=0x02,
                address=CONNECTED_INPUT_BASE,
                count=CONNECTED_INPUT_COUNT,
                operation=lambda active_client: active_client.read_discrete_inputs(
                    CONNECTED_INPUT_BASE,
                    CONNECTED_INPUT_COUNT,
                ),
            )
            diagnostics.append(diagnostic)
            if transport_failed:
                failed_transport_key = "CONNECTED_ABC"

        if connected_result is None:
            connected: dict[str, bool | None] = {"A": None, "B": None, "C": None}
        else:
            connected = dict(zip(("A", "B", "C"), connected_result, strict=True))

        if failed_transport_key is not None:
            status_result = None
            diagnostics.append(
                self._skipped_diagnostic(
                    key="STATUS",
                    function_code=0x03,
                    address=STATUS_REGISTER_BASE,
                    count=STATUS_REGISTER_COUNT,
                    failed_key=failed_transport_key,
                )
            )
        else:
            status_result, diagnostic, _ = self._probe(
                client,
                key="STATUS",
                function_code=0x03,
                address=STATUS_REGISTER_BASE,
                count=STATUS_REGISTER_COUNT,
                operation=lambda active_client: active_client.read_holding_registers(
                    STATUS_REGISTER_BASE,
                    STATUS_REGISTER_COUNT,
                ),
            )
            diagnostics.append(diagnostic)

        if status_result is None:
            error_raw = None
            warning_raw = None
            error_flags = None
            warning_flags = None
        else:
            error_raw, warning_raw = status_result
            error_flags = decode_status_flags(error_raw, ERROR_FLAGS)
            warning_flags = decode_status_flags(warning_raw, WARNING_FLAGS)

        return ModbusDeviceEvidenceValues(
            energy=energy,
            connected=connected,
            error_raw=error_raw,
            warning_raw=warning_raw,
            error_flags=error_flags,
            warning_flags=warning_flags,
            read_diagnostics=tuple(diagnostics),
        )
