import socket

from .protocol import build_read_holding_request, parse_read_holding_response


class ReadOnlyModbusClient:
    """Persistent Modbus/TCP client limited to holding-register reads."""

    def __init__(self, host: str, port: int, unit_id: int, timeout_s: float) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout_s = timeout_s
        self._socket: socket.socket | None = None
        self._transaction_id = 0
        self.connections_opened = 0

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        if self._socket is None:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            sock.settimeout(self.timeout_s)
            self._socket = sock
            self.connections_opened += 1

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def read_holding_registers(self, start_register: int, register_count: int) -> tuple[int, ...]:
        self.connect()
        sock = self._socket
        assert sock is not None
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        request = build_read_holding_request(
            self._transaction_id,
            self.unit_id,
            start_register,
            register_count,
        )
        sock.sendall(request)
        header = self._recv_exact(sock, 7)
        length = int.from_bytes(header[4:6], "big")
        if length < 2:
            raise ConnectionError("invalid Modbus/TCP length field")
        body = self._recv_exact(sock, length - 1)
        return parse_read_holding_response(
            header + body,
            self._transaction_id,
            self.unit_id,
            register_count,
        )

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise ConnectionError("Modbus connection closed")
            chunks.extend(chunk)
        return bytes(chunks)
