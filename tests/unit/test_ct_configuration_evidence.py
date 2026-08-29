from __future__ import annotations

import asyncio

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

    def settimeout(self, _timeout: float) -> None:
        pass

    def recv(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

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
