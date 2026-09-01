from __future__ import annotations

from .protocol import AckFrame, CommandFrame, HelloFrame, StatusFrame


class QualifiedActuatorChannelError(RuntimeError):
    """Raised when no current HELLO-qualified actuator session is available."""


class QualifiedActuatorChannel:
    """Narrow transport channel for one current HELLO-qualified actuator session.

    The channel does not calculate control requests and does not authorize a
    nonzero command. Its only purpose is to keep command transport outside the
    Stage-2 qualification service.
    """

    def __init__(self) -> None:
        self._session = None
        self._hello: HelloFrame | None = None

    def bind(self, session, hello: HelloFrame) -> None:
        if not isinstance(hello, HelloFrame):
            raise ValueError("hello must be HelloFrame")
        if session is None or not bool(getattr(session, "connected", False)):
            raise QualifiedActuatorChannelError("actuator is not HELLO-qualified")
        if self._session is not None:
            raise QualifiedActuatorChannelError("qualified actuator channel is already bound")
        self._session = session
        self._hello = hello

    def clear(self, session=None) -> None:
        if session is not None and session is not self._session:
            return
        self._session = None
        self._hello = None

    def hello(self) -> HelloFrame | None:
        session = self._session
        if session is None or not bool(getattr(session, "connected", False)):
            return None
        return self._hello

    def _qualified_session(self):
        session = self._session
        if (
            session is None
            or self._hello is None
            or not bool(getattr(session, "connected", False))
        ):
            raise QualifiedActuatorChannelError("actuator is not HELLO-qualified")
        return session

    async def send(self, command: CommandFrame) -> None:
        if not isinstance(command, CommandFrame):
            raise ValueError("command must be CommandFrame")
        session = self._qualified_session()
        await session.send_command(command)

    async def receive(self, timeout_s: float) -> AckFrame | StatusFrame:
        session = self._qualified_session()
        return await session.receive_frame(timeout_s)
