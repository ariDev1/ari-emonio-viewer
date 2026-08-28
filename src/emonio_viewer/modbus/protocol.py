import struct


class ModbusProtocolError(RuntimeError):
    """Raised when a Modbus/TCP response violates the expected read contract."""


class ModbusExceptionResponse(ModbusProtocolError):
    """Raised when the server returns a Modbus exception response."""


def build_read_holding_request(
    transaction_id: int,
    unit_id: int,
    start_register: int,
    register_count: int,
) -> bytes:
    if not 0 <= transaction_id <= 0xFFFF:
        raise ValueError("transaction_id must be 0..65535")
    if not 0 <= unit_id <= 0xFF:
        raise ValueError("unit_id must be 0..255")
    if not 0 <= start_register <= 0xFFFF:
        raise ValueError("start_register must be 0..65535")
    if not 1 <= register_count <= 125:
        raise ValueError("register_count must be 1..125")
    if start_register + register_count - 1 > 0xFFFF:
        raise ValueError("requested register range exceeds 65535")

    pdu = struct.pack(">BHH", 0x03, start_register, register_count)
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
