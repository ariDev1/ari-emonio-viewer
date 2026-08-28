import socket
import struct
import threading

from emonio_viewer.modbus.transport import ReadOnlyModbusClient


class SplitResponseSocket:
    """Hold the first response header until another thread closes the client."""

    def __init__(self) -> None:
        self.header_ready = threading.Event()
        self.allow_header_return = threading.Event()
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        pass

    def sendall(self, _data: bytes) -> None:
        pass

    def recv(self, _size: int) -> bytes:
        if not self.header_ready.is_set():
            self.header_ready.set()
            assert self.allow_header_return.wait(1.0)
            return struct.pack(">HHHB", 1, 0, 35, 1)
        if self.closed:
            raise OSError("socket closed during shutdown")
        raise AssertionError("body receive should observe closed socket")

    def shutdown(self, how: int) -> None:
        assert how == socket.SHUT_RDWR
        self.closed = True

    def close(self) -> None:
        self.closed = True


def test_close_during_modbus_response_never_exposes_internal_socket_assertion(monkeypatch) -> None:
    fake_socket = SplitResponseSocket()
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: fake_socket)
    client = ReadOnlyModbusClient("127.0.0.1", 502, 1, 5.0)
    errors: list[BaseException] = []

    def read() -> None:
        try:
            client.read_holding_registers(0, 16)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=read)
    thread.start()
    assert fake_socket.header_ready.wait(1.0)
    client.close()
    fake_socket.allow_header_return.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], OSError)
