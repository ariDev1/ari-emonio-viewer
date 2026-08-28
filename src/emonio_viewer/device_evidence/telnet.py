from __future__ import annotations

import re
import socket
from typing import Iterable

from .model import CtConfigurationValues

TELNET_PORT = 23
DEFAULT_TIMEOUT_S = 5.0
ADMIN_USERNAME = "admin"

FIXED_CT_READS = (
    ("ct_type", "conf ct_type"),
    ("ct_voltage", "conf ct_voltage"),
    ("ct_range", "conf ct_range"),
    ("ct_invert", "conf ct_invert"),
    ("ct_didt", "conf ct_didt"),
)

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240


class CtConfigurationReadError(RuntimeError):
    """Raised when the read-only Emonio CT configuration read cannot complete."""


class _TelnetSocket:
    """Minimal Telnet transport copied from the field-confirmed v0.3.0 probe."""

    def __init__(self, host: str, port: int, timeout_s: float) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout_s)
            self._sock.settimeout(timeout_s)
        except OSError as exc:
            raise CtConfigurationReadError("Telnet connection failed") from exc
        self._clean = bytearray()
        self._pending_iac = False
        self._pending_negotiation: int | None = None
        self._subnegotiation = False
        self._subnegotiation_iac = False

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def send_line(self, text: str) -> None:
        try:
            self._sock.sendall(text.encode("utf-8") + b"\r\n")
        except OSError as exc:
            raise CtConfigurationReadError("Telnet send failed") from exc

    def read_until_any(self, markers: Iterable[bytes], *, max_bytes: int = 65536) -> bytes:
        marker_tuple = tuple(markers)
        while True:
            current = bytes(self._clean)
            if any(marker in current for marker in marker_tuple):
                self._clean.clear()
                return current
            self._recv_and_consume(max_bytes=max_bytes)

    def read_until_integer(self, *, max_bytes: int = 65536) -> int:
        while True:
            current = bytes(self._clean)
            value = extract_integer_if_present(current)
            if value is not None:
                self._clean.clear()
                return value
            self._recv_and_consume(max_bytes=max_bytes)

    def _recv_and_consume(self, *, max_bytes: int) -> None:
        if len(self._clean) >= max_bytes:
            raise CtConfigurationReadError("Telnet response exceeded safety limit")
        try:
            chunk = self._sock.recv(4096)
        except socket.timeout as exc:
            raise CtConfigurationReadError("Timed out waiting for Emonio Telnet response") from exc
        except OSError as exc:
            raise CtConfigurationReadError("Telnet receive failed") from exc
        if not chunk:
            raise CtConfigurationReadError("Emonio closed the Telnet connection")
        self._consume(chunk)
        if len(self._clean) >= max_bytes:
            raise CtConfigurationReadError("Telnet response exceeded safety limit")

    def _send_negotiation(self, command: int, option: int) -> None:
        try:
            self._sock.sendall(bytes((IAC, command, option)))
        except OSError as exc:
            raise CtConfigurationReadError("Telnet negotiation failed") from exc

    def _consume(self, data: bytes) -> None:
        index = 0
        while index < len(data):
            byte = data[index]

            if self._subnegotiation:
                if self._subnegotiation_iac:
                    self._subnegotiation_iac = False
                    if byte == SE:
                        self._subnegotiation = False
                    elif byte == IAC:
                        pass
                    index += 1
                    continue
                if byte == IAC:
                    self._subnegotiation_iac = True
                index += 1
                continue

            if self._pending_negotiation is not None:
                command = self._pending_negotiation
                self._pending_negotiation = None
                if command == WILL:
                    self._send_negotiation(DONT, byte)
                elif command == DO:
                    self._send_negotiation(WONT, byte)
                index += 1
                continue

            if self._pending_iac:
                self._pending_iac = False
                command = byte
                index += 1
                if command in (WILL, WONT, DO, DONT):
                    if index >= len(data):
                        self._pending_negotiation = command
                    else:
                        option = data[index]
                        if command == WILL:
                            self._send_negotiation(DONT, option)
                        elif command == DO:
                            self._send_negotiation(WONT, option)
                        index += 1
                elif command == SB:
                    self._subnegotiation = True
                elif command == IAC:
                    self._clean.append(IAC)
                continue

            if byte == IAC:
                self._pending_iac = True
                index += 1
                continue

            self._clean.append(byte)
            index += 1


def extract_integer_if_present(response: bytes) -> int | None:
    """Return one complete standalone integer result without range interpretation."""
    match = re.search(rb"(?:^|[\r\n])[ \t]*([+-]?\d+)[ \t]*(?=[\r\n])", response)
    if match is None:
        return None
    return int(match.group(1), 10)


class TelnetCtConfigurationReader:
    """Read the five field-proven CT keys. No arbitrary CLI command is exposed."""

    def __init__(self, *, port: int = TELNET_PORT, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._port = port
        self._timeout_s = timeout_s

    def read(self, host: str, password: str) -> CtConfigurationValues:
        session = _TelnetSocket(host, self._port, self._timeout_s)
        try:
            session.read_until_any((b"login:", b"Login:"))
            session.send_line(ADMIN_USERNAME)
            session.read_until_any((b"Password:", b"password:"))
            session.send_line(password)
            login_response = session.read_until_any((b"$ ", b"# "))
            lowered = login_response.lower()
            if b"incorrect" in lowered or b"failed" in lowered or b"login:" in lowered:
                raise CtConfigurationReadError("Emonio Telnet login failed")

            raw: dict[str, int] = {}
            for key, command in FIXED_CT_READS:
                session.send_line(command)
                raw[key] = session.read_until_integer()
            return CtConfigurationValues(**raw)
        finally:
            session.close()
