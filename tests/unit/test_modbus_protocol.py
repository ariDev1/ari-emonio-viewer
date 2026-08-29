import struct
import pytest

from emonio_viewer.modbus.protocol import (
    ModbusExceptionResponse,
    ModbusProtocolError,
    build_read_discrete_inputs_request,
    build_read_holding_request,
    parse_read_discrete_inputs_response,
    parse_read_holding_response,
)
from tests.fixtures.modbus_frames import make_response


def test_builds_only_function_03_read_request() -> None:
    request = build_read_holding_request(7, 1, 100, 16)
    assert request[7] == 0x03
    assert request[-4:] == struct.pack(">HH", 100, 16)


def test_parses_two_registers() -> None:
    raw = make_response(7, 1, 0x03, b"\x04\x12\x34\xAB\xCD")
    assert parse_read_holding_response(raw, 7, 1, 2) == (0x1234, 0xABCD)


def test_rejects_wrong_transaction_id() -> None:
    raw = make_response(8, 1, 0x03, b"\x04\x12\x34\xAB\xCD")
    with pytest.raises(ModbusProtocolError, match="transaction"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_wrong_protocol_id() -> None:
    raw = make_response(7, 1, 0x03, b"\x04\x12\x34\xAB\xCD", protocol_id=1)
    with pytest.raises(ModbusProtocolError, match="protocol"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_wrong_unit_id() -> None:
    raw = make_response(7, 2, 0x03, b"\x04\x12\x34\xAB\xCD")
    with pytest.raises(ModbusProtocolError, match="unit"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_wrong_function_code() -> None:
    raw = make_response(7, 1, 0x04, b"\x04\x12\x34\xAB\xCD")
    with pytest.raises(ModbusProtocolError, match="function"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_wrong_byte_count() -> None:
    raw = make_response(7, 1, 0x03, b"\x02\x12\x34")
    with pytest.raises(ModbusProtocolError, match="byte count"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_truncated_frame() -> None:
    raw = make_response(7, 1, 0x03, b"\x04\x12\x34\xAB\xCD")[:-1]
    with pytest.raises(ModbusProtocolError, match="length|truncated"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_reports_modbus_exception() -> None:
    raw = make_response(7, 1, 0x83, b"\x02")
    with pytest.raises(ModbusExceptionResponse, match="exception code 2"):
        parse_read_holding_response(raw, 7, 1, 2)


def test_rejects_invalid_request_register_count() -> None:
    with pytest.raises(ValueError, match="register_count"):
        build_read_holding_request(1, 1, 0, 0)


def test_builds_function_02_discrete_input_request() -> None:
    request = build_read_discrete_inputs_request(9, 1, 0, 3)
    assert request[7] == 0x02
    assert request[-4:] == struct.pack(">HH", 0, 3)


def test_parses_three_discrete_input_bits_lsb_first() -> None:
    raw = make_response(9, 1, 0x02, b"\x01\x05")
    assert parse_read_discrete_inputs_response(raw, 9, 1, 3) == (True, False, True)


def test_discrete_input_parser_rejects_nonzero_unused_bits() -> None:
    raw = make_response(9, 1, 0x02, b"\x01\x85")
    with pytest.raises(ModbusProtocolError, match="unused"):
        parse_read_discrete_inputs_response(raw, 9, 1, 3)
