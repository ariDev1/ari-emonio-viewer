import struct


def make_response(transaction_id: int, unit_id: int, function: int, payload: bytes, protocol_id: int = 0) -> bytes:
    pdu = bytes([function]) + payload
    return struct.pack(">HHHB", transaction_id, protocol_id, len(pdu) + 1, unit_id) + pdu
