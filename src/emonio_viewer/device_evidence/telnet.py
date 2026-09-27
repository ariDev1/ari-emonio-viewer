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

# Read-only system-information commands. "info version" is tried first;
# "info device" is only a fallback source for the same Version: evidence.
FIRMWARE_INFO_COMMANDS = ("info version", "info device")

# Markers that terminate a command response at the next shell prompt.
_PROMPT_MARKERS = (b"$ ", b"# ")

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240


class CtConfigurationReadError(RuntimeError):
    """Read-only CT evidence failure with a safe operator-facing state."""

    def __init__(
        self,
        message: str,
        *,
        state: str = "READ_ERROR",
        stage: str = "READ",
        user_message: str = "CT configuration read failed.",
    ) -> None:
        super().__init__(message)
        self.state = state
        self.stage = stage
        self.user_message = user_message


class _TelnetSocket:
    """Minimal Telnet transport copied from the field-confirmed v0.3.0 probe."""

    def __init__(self, host: str, port: int, timeout_s: float) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout_s)
            self._sock.settimeout(timeout_s)
        except OSError as exc:
            raise CtConfigurationReadError(
                "Telnet connection failed",
                state="TELNET_UNAVAILABLE",
                stage="CONNECT",
                user_message=(
                    "Telnet is unavailable. The Emonio Telnet service must be enabled before reading "
                    "CT configuration. Normal Modbus measurements and SCOPE are not affected."
                ),
            ) from exc
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
        if "\r" in text or "\n" in text:
            raise CtConfigurationReadError("Telnet credential contains line break")
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

    def read_until_text(self, needle: bytes, *, max_bytes: int = 65536) -> bytes:
        """Consume input until the full needle (e.g. a command echo) arrived.

        ANSI redraw sequences are ignored for matching: the device may split
        echoed bytes with escape codes.
        """
        if not needle:
            raise CtConfigurationReadError("Telnet match text must not be empty")
        while True:
            current = bytes(self._clean)
            if needle in strip_terminal_sequences(current):
                self._clean.clear()
                return current
            self._recv_and_consume(max_bytes=max_bytes)

    def read_until_prompt(
        self,
        echo: bytes,
        *,
        markers: tuple[bytes, ...] = _PROMPT_MARKERS,
        grace_s: float = 0.3,
        max_bytes: int = 65536,
    ) -> bytes:
        """Read a full command response up to the final shell prompt.

        The device redraws the prompt with partial input and may re-echo
        the full command line; both contain prompt markers that must not
        end the read early. Buffered bytes are never discarded mid-read:
        echo, output, and prompt may arrive in a single chunk. A response
        is only accepted when the buffered bytes end with a prompt marker
        and no further bytes arrive within the grace window.
        """
        while echo not in strip_terminal_sequences(bytes(self._clean)):
            self._recv_and_consume(max_bytes=max_bytes)
        bare_markers = tuple(marker.rstrip() for marker in markers)
        while True:
            clean = strip_terminal_sequences(bytes(self._clean))
            if clean.endswith(markers) or clean.rstrip().endswith(bare_markers):
                if self._quiescent(grace_s):
                    response = bytes(self._clean)
                    self._clean.clear()
                    return response
            self._recv_and_consume(max_bytes=max_bytes)

    def _quiescent(self, grace_s: float) -> bool:
        """Return True when no further bytes arrive within the grace window.

        Uses MSG_PEEK so a negative answer never consumes bytes that belong
        to subsequent reads.
        """
        previous = self._sock.gettimeout()
        self._sock.settimeout(grace_s)
        try:
            try:
                chunk = self._sock.recv(4096, socket.MSG_PEEK)
            except socket.timeout:
                return True
            except OSError as exc:
                raise CtConfigurationReadError("Telnet receive failed") from exc
        finally:
            try:
                self._sock.settimeout(previous)
            except OSError:
                pass
        if not chunk:
            raise CtConfigurationReadError("Emonio closed the Telnet connection")
        return False

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


_ANSI_CSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


def strip_terminal_sequences(data: bytes) -> bytes:
    """Remove ANSI escape sequences from interactive Telnet command output."""
    return _ANSI_CSI.sub(b"", data)


class TelnetCtConfigurationReader:
    """Read the five field-proven CT keys. No arbitrary CLI command is exposed."""

    def __init__(self, *, port: int = TELNET_PORT, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._port = port
        self._timeout_s = timeout_s

    @staticmethod
    def _stage(stage: str, operation):
        try:
            return operation()
        except CtConfigurationReadError as exc:
            if exc.state != "READ_ERROR" or exc.stage != "READ":
                raise
            raise CtConfigurationReadError(
                str(exc),
                state="READ_ERROR",
                stage=stage,
                user_message=f"CT configuration read failed during {stage}.",
            ) from exc

    def read(self, host: str, password: str) -> CtConfigurationValues:
        values, _firmware, _detail = self.read_with_firmware(host, password)
        return values

    def read_with_firmware(
        self, host: str, password: str
    ) -> tuple[CtConfigurationValues, str | None, str]:
        """Read CT keys plus best-effort firmware over one Telnet session.

        Returns (values, firmware_version_or_None, firmware_detail). A missing
        firmware string never fails the CT read; CT failures still raise.
        """
        session = _TelnetSocket(host, self._port, self._timeout_s)
        try:
            self._login(session, password)
            raw: dict[str, int] = {}
            for key, command in FIXED_CT_READS:
                stage = key.upper()
                self._stage(stage, lambda command=command: session.send_line(command))
                raw[key] = self._stage(stage, session.read_until_integer)
            firmware, detail = self._read_firmware_best_effort(session)
            return CtConfigurationValues(**raw), firmware, detail
        finally:
            session.close()

    def _login(self, session: _TelnetSocket, password: str) -> None:
        self._stage("LOGIN_PROMPT", lambda: session.read_until_any((b"login:", b"Login:")))
        self._stage("USERNAME", lambda: session.send_line(ADMIN_USERNAME))
        self._stage("PASSWORD_PROMPT", lambda: session.read_until_any((b"Password:", b"password:")))
        self._stage("PASSWORD", lambda: session.send_line(password))
        login_response = self._stage(
            "AUTH",
            lambda: session.read_until_any(
                (b"$ ", b"# ", b"login:", b"Login:", b"incorrect", b"failed")
            ),
        )
        lowered = login_response.lower()
        if b"incorrect" in lowered or b"failed" in lowered or b"login:" in lowered:
            raise CtConfigurationReadError(
                "Emonio Telnet login failed",
                state="AUTH_FAILED",
                stage="AUTH",
                user_message=(
                    "Telnet authentication failed for user admin. "
                    "Check the Emonio admin password."
                ),
            )

    def _read_firmware_best_effort(self, session: _TelnetSocket) -> tuple[str | None, str]:
        # Firmware evidence must never break the CT read. Any unexpected
        # failure degrades to "not found", never to an exception.
        try:
            return self._read_firmware_unsafe(session)
        except Exception as exc:
            return None, f"RESPONSE_NOT_READABLE: {type(exc).__name__}"

    def _read_firmware_unsafe(self, session: _TelnetSocket) -> tuple[str | None, str]:
        from .firmware import parse_firmware_version

        last_raw = ""
        for command in FIRMWARE_INFO_COMMANDS:
            encoded = command.encode("utf-8")
            try:
                session.send_line(command)
            except CtConfigurationReadError as exc:
                return None, f"RESPONSE_NOT_READABLE: send failed: {exc}"
            try:
                response = session.read_until_prompt(encoded)
            except CtConfigurationReadError as exc:
                return None, f"RESPONSE_NOT_READABLE: prompt not completed: {exc}"
            clean = strip_terminal_sequences(response).decode("utf-8", errors="replace")
            last_raw = clean
            version = parse_firmware_version(clean)
            if version is not None:
                return version, "OBSERVED_VIA_TELNET_INFO"
        snippet = " ".join(last_raw.split())[:160]
        return None, f"VERSION_NOT_FOUND: {snippet or 'empty response'}"
