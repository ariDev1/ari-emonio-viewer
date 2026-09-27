from __future__ import annotations

import asyncio
import socket

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from emonio_viewer.device_evidence.model import CtConfigurationEvidence, CtConfigurationValues
from emonio_viewer.device_evidence.service import CtConfigurationService
from emonio_viewer.device_evidence.telnet import (
    FIXED_CT_READS,
    IAC,
    WILL,
    CtConfigurationReadError,
    TelnetCtConfigurationReader,
    extract_integer_if_present,
)

PROMPT = b"admin@emonio-example:~$ "
REDRAW_ONLY = (
    b"\r" + PROMPT + b"c"
    b"\r" + PROMPT + b"co"
    b"\r" + PROMPT + b"con"
    b"\r" + PROMPT + b"conf"
)


def _command_result(command: str, value: int) -> bytes:
    return (
        b"\r"
        + PROMPT
        + command.encode("ascii")
        + b"\r\n"
        + str(value).encode("ascii")
        + b"\r\n"
        + PROMPT
    )


class FakeSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.sent: list[bytes] = []
        self.closed = False
        self._timeout: float | None = None
        self.grace_timeout_on_empty = False

    def settimeout(self, timeout: float) -> None:
        self._timeout = timeout

    def gettimeout(self) -> float | None:
        return self._timeout

    def recv(self, _size: int, _flags: int = 0) -> bytes:
        if not self._chunks:
            if self.grace_timeout_on_empty:
                raise socket.timeout("timed out")
            return b""
        if _flags & socket.MSG_PEEK:
            return self._chunks[0]
        return self._chunks.pop(0)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


def test_telnet_parser_ignores_prompt_redraw_and_waits_for_integer_line() -> None:
    assert extract_integer_if_present(REDRAW_ONLY) is None
    assert extract_integer_if_present(REDRAW_ONLY + b"\r\n7\r\n") == 7


def test_telnet_parser_preserves_raw_integer_without_mapping_or_range_guess() -> None:
    assert extract_integer_if_present(b"\r\n11100\r\n") == 11100
    assert extract_integer_if_present(b"\r\n-12\r\n") == -12


def test_fixed_telnet_reads_are_exactly_the_field_proven_five_commands() -> None:
    assert FIXED_CT_READS == (
        ("ct_type", "conf ct_type"),
        ("ct_voltage", "conf ct_voltage"),
        ("ct_range", "conf ct_range"),
        ("ct_invert", "conf ct_invert"),
        ("ct_didt", "conf ct_didt"),
    )


def test_telnet_reader_uses_one_login_and_only_fixed_read_commands() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = [
        bytes((IAC, WILL, 1)) + b"Emonio login: ",
        b"Password: ",
        b"\r\n" + PROMPT,
    ]
    for key, command in FIXED_CT_READS:
        chunks.extend([REDRAW_ONLY, _command_result(command, expected[key])])
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values = TelnetCtConfigurationReader(timeout_s=1.0).read("192.0.2.1", "secret")

    assert values == CtConfigurationValues(**expected)
    sent_conf = [item for item in fake.sent if item.startswith(b"conf ")]
    assert sent_conf == [command.encode("ascii") + b"\r\n" for _key, command in FIXED_CT_READS]
    assert fake.closed is True


def test_telnet_connection_failure_is_classified_as_unavailable() -> None:
    with patch(
        "emonio_viewer.device_evidence.telnet.socket.create_connection",
        side_effect=ConnectionRefusedError(111, "Connection refused"),
    ):
        with pytest.raises(CtConfigurationReadError) as caught:
            TelnetCtConfigurationReader(timeout_s=1.0).read("192.0.2.1", "secret")

    assert caught.value.state == "TELNET_UNAVAILABLE"
    assert caught.value.stage == "CONNECT"
    assert "Telnet" in caught.value.user_message
    assert "enabled" in caught.value.user_message
    assert "secret" not in caught.value.user_message


def test_explicit_telnet_login_rejection_is_classified_as_auth_failed() -> None:
    fake = FakeSocket([
        b"Emonio login: ",
        b"Password: ",
        b"\r\nLogin incorrect\r\nEmonio login: ",
    ])

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        with pytest.raises(CtConfigurationReadError) as caught:
            TelnetCtConfigurationReader(timeout_s=1.0).read("192.0.2.1", "wrong-secret")

    assert caught.value.state == "AUTH_FAILED"
    assert caught.value.stage == "AUTH"
    assert "admin" in caught.value.user_message
    assert "wrong-secret" not in caught.value.user_message
    assert fake.closed is True


def test_ct_command_failure_reports_exact_read_stage_without_password() -> None:
    fake = FakeSocket([
        b"Emonio login: ",
        b"Password: ",
        b"\r\n" + PROMPT,
        b"",
    ])

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        with pytest.raises(CtConfigurationReadError) as caught:
            TelnetCtConfigurationReader(timeout_s=1.0).read("192.0.2.1", "secret")

    assert caught.value.state == "READ_ERROR"
    assert caught.value.stage == "CT_TYPE"
    assert "secret" not in caught.value.user_message


def test_evidence_model_reports_raw_device_configuration_and_no_physical_claim() -> None:
    evidence = CtConfigurationEvidence(
        device_id="emonio-example",
        observed_utc=datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc),
        values=CtConfigurationValues(0, 0, 3, 7, 0),
    )
    payload = evidence.as_dict()

    assert payload["source"] == "EMONIO_TELNET_CONF"
    assert payload["transport"] == "TELNET"
    assert payload["interpretation"] == "RAW_DEVICE_CONFIGURATION"
    assert payload["physical_orientation_status"] == "NOT_VERIFIED"
    assert payload["values"] == {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }


def test_service_caches_evidence_but_does_not_retain_password() -> None:
    class FakeReader:
        def __init__(self) -> None:
            self.calls = []

        def read(self, host: str, password: str):
            self.calls.append((host, password))
            return CtConfigurationValues(0, 0, 3, 7, 0)

    reader = FakeReader()
    when = datetime(2026, 8, 27, 20, 1, tzinfo=timezone.utc)
    service = CtConfigurationService(reader, clock=lambda: when)
    evidence = asyncio.run(service.read("device-1", "192.0.2.10", "top-secret"))

    assert reader.calls == [("192.0.2.10", "top-secret")]
    assert service.get("device-1") == evidence
    assert "top-secret" not in repr(service.__dict__)


def test_service_keeps_last_successful_evidence_when_later_read_fails() -> None:
    class OneSuccessThenFailureReader:
        def __init__(self) -> None:
            self.calls = 0

        def read(self, _host: str, _password: str):
            self.calls += 1
            if self.calls == 1:
                return CtConfigurationValues(0, 0, 3, 7, 0)
            from emonio_viewer.device_evidence.telnet import CtConfigurationReadError
            raise CtConfigurationReadError("simulated later failure")

    reader = OneSuccessThenFailureReader()
    service = CtConfigurationService(reader)
    first = asyncio.run(service.read("device-1", "192.0.2.10", "secret"))

    try:
        asyncio.run(service.read("device-1", "192.0.2.10", "secret"))
    except Exception:
        pass
    else:
        raise AssertionError("second read must fail")

    assert service.get("device-1") == first


def _login_chunks() -> list:
    return [
        bytes((IAC, WILL, 1)) + b"Emonio login: ",
        b"Password: ",
        b"\r\n" + PROMPT,
    ]


def _ct_chunks(expected: dict) -> list:
    chunks = []
    for key, command in FIXED_CT_READS:
        chunks.extend([REDRAW_ONLY, _command_result(command, expected[key])])
    return chunks


def _firmware_chunks(command: str, output: bytes) -> list:
    redraw = b"\r" + PROMPT + b"i\x1b[0K \x1b[24C"
    echo = b"\r" + PROMPT + command.encode("ascii")
    return [redraw, echo, b"\r\n" + output + b"\r\n" + PROMPT]


def test_telnet_info_version_reports_device_firmware_in_same_session() -> None:
    from emonio_viewer.device_evidence.telnet import FIRMWARE_INFO_COMMANDS

    assert FIRMWARE_INFO_COMMANDS[0] == "info version"
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.extend(_firmware_chunks("info version", b"Version: 3.0.80-release\x1b[0K"))
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values, firmware, detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert values == CtConfigurationValues(**expected)
    assert firmware == "3.0.80-release"
    assert detail == "OBSERVED_VIA_TELNET_INFO"
    assert b"info version\r\n" in fake.sent
    assert fake.closed is True


def test_telnet_ansi_split_echo_and_trailing_codes_do_not_break_read() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.append(b"\r" + PROMPT + b"info \x1b[0K\x1b[24Cversion")
    chunks.append(b"\r\nVersion: 3.0.80-release\x1b[0K\r\n" + PROMPT + b"\x1b[0K")
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values, firmware, _detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert values == CtConfigurationValues(**expected)
    assert firmware == "3.0.80-release"


def test_telnet_single_chunk_echo_output_prompt_is_not_discarded() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.append(
        b"\r" + PROMPT + b"info version\r\nVersion: 3.0.80-release\r\n" + PROMPT
    )
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values, firmware, _detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert values == CtConfigurationValues(**expected)
    assert firmware == "3.0.80-release"


def test_telnet_prompt_in_echo_does_not_truncate_firmware_read() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.append(b"\r" + PROMPT + b"i\x1b[0K \x1b[24C")
    chunks.append(b"\r" + PROMPT + b"info version")
    chunks.append(b"\r\n" + PROMPT + b"info version")
    chunks.append(b"\r\nVersion: 3.0.80-release\r\n" + PROMPT)
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values, firmware, _detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert values == CtConfigurationValues(**expected)
    assert firmware == "3.0.80-release"


def test_telnet_real_emonio_version_response_ignores_continuing_prompt_redraws() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.append(b"\r" + PROMPT + b"info version")
    chunks.append(
        b"\r\n\r\nVERSION\r\n\r\n Hardware: 2.1\r\n"
        b" Firmware: 3.0.80-release (ger)\r\n"
        b" CRC32: 87eac5b5\r\n"
        b" Source: 3.0.80-4-gc7e8d903\r\n"
        b" Core: 3.0.7-78-g5afbb3804\r\n"
        b" SDK: v5.1.5-346-g41a885bb2d\r\n"
        b" Build: 2026-09-17 21:00:51\r\n\r\n"
        + PROMPT
    )
    # Field evidence shows the interactive terminal keeps redrawing after the
    # completed command response. These bytes must not delay response completion.
    chunks.append(b"\r" + PROMPT + b"\x1b[0K")
    chunks.append(b"\r" + PROMPT + b"\x1b[0K")
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        _values, firmware, _detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert firmware == "3.0.80-release"


def test_telnet_firmware_falls_back_to_info_device() -> None:
    expected = {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    chunks = _login_chunks() + _ct_chunks(expected)
    chunks.extend(_firmware_chunks("info version", b"no version here"))
    chunks.extend(_firmware_chunks("info device", b"device: emonio-63a834 Version: 3.0.80-release"))
    fake = FakeSocket(chunks)
    fake.grace_timeout_on_empty = True

    with patch("emonio_viewer.device_evidence.telnet.socket.create_connection", return_value=fake):
        values, firmware, _detail = TelnetCtConfigurationReader(timeout_s=1.0).read_with_firmware(
            "192.0.2.1", "secret"
        )

    assert values == CtConfigurationValues(**expected)
    assert firmware == "3.0.80-release"
