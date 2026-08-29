import struct


class ModbusProtocolError(RuntimeError):
    """Raised when a Modbus/TCP response violates the expected read contract."""


class ModbusExceptionResponse(ModbusProtocolError):
    """Raised when the server returns a Modbus exception response."""


def _validate_read_request(
    transaction_id: int,
    unit_id: int,
    start_address: int,
    count: int,
    *,
    count_name: str,
    max_count: int,
) -> None:
    if not 0 <= transaction_id <= 0xFFFF:
        raise ValueError("transaction_id must be 0..65535")
    if not 0 <= unit_id <= 0xFF:
        raise ValueError("unit_id must be 0..255")
    if not 0 <= start_address <= 0xFFFF:
        raise ValueError("start_register must be 0..65535")
    if not 1 <= count <= max_count:
        raise ValueError(f"{count_name} must be 1..{max_count}")
    if start_address + count - 1 > 0xFFFF:
        raise ValueError("requested range exceeds 65535")


def build_read_holding_request(
    transaction_id: int,
    unit_id: int,
    start_register: int,
    register_count: int,
) -> bytes:
    _validate_read_request(
        transaction_id,
        unit_id,
        start_register,
        register_count,
        count_name="register_count",
        max_count=125,
    )
    pdu = struct.pack(">BHH", 0x03, start_register, register_count)
    return struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id) + pdu


def build_read_discrete_inputs_request(
    transaction_id: int,
    unit_id: int,
    start_input: int,
    input_count: int,
) -> bytes:
    _validate_read_request(
        transaction_id,
        unit_id,
        start_input,
        input_count,
        count_name="input_count",
        max_count=2000,
    )
    pdu = struct.pack(">BHH", 0x02, start_input, input_count)
    return struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id) + pdu


def parse_read_holding_response(
    raw: bytes,
    transaction_id: int,
    unit_id: int,
    register_count: int,
) -> tuple[int, ...]:
    if len(raw) < 9:
        raise ModbusProtocolError("truncated response")

    tx, protocol, length, actual_unit = struct.unpack(">HHHB", raw[:7])
    if tx != transaction_id:
        raise ModbusProtocolError("transaction id mismatch")
    if protocol != 0:
        raise ModbusProtocolError("protocol id mismatch")
    if actual_unit != unit_id:
        raise ModbusProtocolError("unit id mismatch")
    if length < 3:
        raise ModbusProtocolError("response length field too small")
    if len(raw) != 6 + length:
        raise ModbusProtocolError("response length mismatch")

    function = raw[7]
    if function == 0x83:
        if len(raw) != 9:
            raise ModbusProtocolError("invalid exception response length")
        raise ModbusExceptionResponse(f"exception code {raw[8]}")
    if function != 0x03:
        raise ModbusProtocolError("function code mismatch")

    byte_count = raw[8]
    expected_bytes = register_count * 2
    if byte_count != expected_bytes:
        raise ModbusProtocolError("byte count mismatch")
    payload = raw[9:]
    if len(payload) != expected_bytes:
        raise ModbusProtocolError("truncated register payload")
    return struct.unpack(">" + "H" * register_count, payload)


def parse_read_discrete_inputs_response(
    raw: bytes,
    transaction_id: int,
    unit_id: int,
    input_count: int,
) -> tuple[bool, ...]:
    if len(raw) < 9:
        raise ModbusProtocolError("truncated response")

    tx, protocol, length, actual_unit = struct.unpack(">HHHB", raw[:7])
    if tx != transaction_id:
        raise ModbusProtocolError("transaction id mismatch")
    if protocol != 0:
        raise ModbusProtocolError("protocol id mismatch")
    if actual_unit != unit_id:
        raise ModbusProtocolError("unit id mismatch")
    if length < 3:
        raise ModbusProtocolError("response length field too small")
    if len(raw) != 6 + length:
        raise ModbusProtocolError("response length mismatch")

    function = raw[7]
    if function == 0x82:
        if len(raw) != 9:
            raise ModbusProtocolError("invalid exception response length")
        raise ModbusExceptionResponse(f"exception code {raw[8]}")
    if function != 0x02:
        raise ModbusProtocolError("function code mismatch")

    expected_bytes = (input_count + 7) // 8
    byte_count = raw[8]
    if byte_count != expected_bytes:
        raise ModbusProtocolError("byte count mismatch")
    payload = raw[9:]
    if len(payload) != expected_bytes:
        raise ModbusProtocolError("truncated discrete input payload")

    unused_bits = expected_bytes * 8 - input_count
    if unused_bits:
        valid_mask = (1 << (8 - unused_bits)) - 1
        if payload[-1] & ~valid_mask:
            raise ModbusProtocolError("unused discrete input bits are nonzero")

    return tuple(
        bool(payload[index // 8] & (1 << (index % 8)))
        for index in range(input_count)
    )
