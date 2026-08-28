import socket
import struct
import threading
import time


class FakeEmonioServer:
    """Deterministic test server that accepts read-holding-register requests only."""

    def __init__(self) -> None:
        self._blocks: dict[int, tuple[int, ...]] = {}
        self._fail_once: dict[int, str] = {}
        self._fail_all_mode: str | None = None
        self.requested_bases: list[int] = []
        self.connection_count = 0
        self.request_count = 0
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self.host, self.port = self._listener.getsockname()
        self._listener.listen()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._started = False
        self._closed = False

    def set_block(self, base: int, words: tuple[int, ...]) -> None:
        assert len(words) == 16
        self._blocks[base] = words

    def fail_next_read(self, base: int, mode: str) -> None:
        assert mode in {"timeout", "exception"}
        self._fail_once[base] = mode

    def fail_all_reads(self, mode: str) -> None:
        assert mode in {"timeout", "exception"}
        self._fail_all_mode = mode

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._thread.start()

    def stop(self) -> None:
        if self._closed:
            return
        self._stop.set()
        try:
            socket.create_connection((self.host, self.port), timeout=0.1).close()
        except OSError:
            pass
        if self._started:
            self._thread.join(timeout=1.0)
        self._listener.close()
        self._closed = True

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            if self._stop.is_set():
                conn.close()
                return
            self.connection_count += 1
            threading.Thread(target=self._serve_connection, args=(conn,), daemon=True).start()

    def _serve_connection(self, conn: socket.socket) -> None:
        with conn:
            while not self._stop.is_set():
                header = self._recv_exact(conn, 7)
                if header is None:
                    return
                tx, protocol, length, unit = struct.unpack(">HHHB", header)
                body = self._recv_exact(conn, length - 1)
                if body is None:
                    return
                function, base, count = struct.unpack(">BHH", body)
                assert protocol == 0
                assert function == 0x03
                assert count == 16
                self.request_count += 1
                self.requested_bases.append(base)
                mode = self._fail_once.pop(base, None) or self._fail_all_mode
                if mode == "timeout":
                    time.sleep(0.25)
                    return
                if mode == "exception":
                    pdu = bytes([0x83, 0x02])
                else:
                    words = self._blocks[base]
                    payload = struct.pack(">" + "H" * 16, *words)
                    pdu = bytes([0x03, len(payload)]) + payload
                response = struct.pack(">HHHB", tx, 0, len(pdu) + 1, unit) + pdu
                conn.sendall(response)

    @staticmethod
    def _recv_exact(conn: socket.socket, size: int) -> bytes | None:
        data = bytearray()
        while len(data) < size:
            try:
                chunk = conn.recv(size - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)
