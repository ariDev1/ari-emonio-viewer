from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from .client import EmonioScopeClient
from .model import ScopeCapture, ScopeSessionState, ScopeStatus
from .protocol import SCOPE_REQUEST_INTERVAL_S


class ScopeServiceError(RuntimeError):
    """Raised when a scope session cannot be created or controlled."""


class ScopeSessionConflict(ScopeServiceError):
    """Raised when a device already owns an active scope session."""


ClientFactory = Callable[[str, str, str], Awaitable[EmonioScopeClient]]
FirmwareSink = Callable[[str, str], None]
"""Receives device-observed firmware evidence as (device_id, version)."""


@dataclass(slots=True)
class _Runtime:
    device_id: str
    state: ScopeSessionState
    client: EmonioScopeClient | None = None
    task: asyncio.Task | None = None
    live_event: asyncio.Event | None = None
    capture: ScopeCapture | None = None
    error: str | None = None
    sequence: int = 0
    firmware: str | None = None
    firmware_detail: str | None = None


class ScopeService:
    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        interval_s: float = SCOPE_REQUEST_INTERVAL_S,
        listen_s: float = 2.0,
        firmware_sink: FirmwareSink | None = None,
    ) -> None:
        if interval_s < 0:
            raise ValueError("scope interval must not be negative")
        if listen_s <= 0:
            raise ValueError("scope listen time must be greater than zero")
        if firmware_sink is not None and not callable(firmware_sink):
            raise ValueError("firmware_sink must be callable")
        self._client_factory = client_factory or EmonioScopeClient.connect
        self._interval_s = interval_s
        self._listen_s = listen_s
        self._firmware_sink = firmware_sink
        self._sessions: dict[str, _Runtime] = {}

    def status(self, device_id: str) -> ScopeStatus:
        runtime = self._sessions.get(device_id)
        if runtime is None:
            return ScopeStatus(device_id, ScopeSessionState.DISCONNECTED, None, None)
        return ScopeStatus(
            device_id,
            runtime.state,
            runtime.error,
            runtime.capture,
            runtime.firmware,
            runtime.firmware_detail,
        )

    def active_statuses(self) -> tuple[ScopeStatus, ...]:
        active_states = {
            ScopeSessionState.CONNECTING,
            ScopeSessionState.LIVE,
            ScopeSessionState.HOLD,
        }
        return tuple(
            self.status(device_id)
            for device_id in sorted(self._sessions)
            if self._sessions[device_id].state in active_states
        )

    async def start(self, device_id: str, host: str, username: str, password: str) -> ScopeStatus:
        current = self._sessions.get(device_id)
        if current is not None and current.state in {
            ScopeSessionState.CONNECTING,
            ScopeSessionState.LIVE,
            ScopeSessionState.HOLD,
        }:
            raise ScopeSessionConflict(f"scope session already active for {device_id}")

        runtime = _Runtime(device_id=device_id, state=ScopeSessionState.CONNECTING)
        self._sessions[device_id] = runtime
        try:
            client = await self._client_factory(host, username, password)
        except Exception as exc:
            if self._sessions.get(device_id) is not runtime or runtime.state is not ScopeSessionState.CONNECTING:
                raise ScopeServiceError(f"scope session start cancelled for {device_id}") from exc
            runtime.state = ScopeSessionState.ERROR
            runtime.error = str(exc) or type(exc).__name__
            raise ScopeServiceError(runtime.error) from exc
        finally:
            username = ""
            password = ""

        if self._sessions.get(device_id) is not runtime or runtime.state is not ScopeSessionState.CONNECTING:
            cancelled = f"scope session start cancelled for {device_id}"
            try:
                await client.close()
            except Exception as exc:
                cleanup_error = str(exc) or type(exc).__name__
                raise ScopeServiceError(f"{cancelled}; cleanup failed: {cleanup_error}") from exc
            raise ScopeServiceError(cancelled)

        runtime.client = client
        runtime.live_event = asyncio.Event()
        runtime.live_event.set()
        runtime.state = ScopeSessionState.LIVE
        runtime.error = None
        runtime.task = asyncio.create_task(self._run(runtime), name=f"emonio-scope-{device_id}")
        await self._report_firmware(device_id, client)
        return self.status(device_id)

    async def _report_firmware(self, device_id: str, client: EmonioScopeClient) -> None:
        """Best-effort firmware evidence; a scope start never fails because of it."""
        runtime = self._sessions.get(device_id)
        fetch = getattr(client, "fetch_firmware", None)
        if not callable(fetch):
            if runtime is not None:
                runtime.firmware_detail = "CLIENT_HAS_NO_FIRMWARE_FETCH"
            return
        try:
            version = await asyncio.wait_for(fetch(), timeout=4.0)
        except Exception as exc:
            if runtime is not None:
                runtime.firmware_detail = f"FETCH_FAILED: {type(exc).__name__}: {exc}"
            return
        if not isinstance(version, str) or not version:
            if runtime is not None:
                runtime.firmware_detail = "FETCH_RETURNED_EMPTY"
            return
        if runtime is not None:
            runtime.firmware = version
            runtime.firmware_detail = "OBSERVED_VIA_SCOPE_SESSION"
        if self._firmware_sink is None:
            return
        try:
            self._firmware_sink(device_id, version)
        except Exception:
            pass

    def hold(self, device_id: str) -> ScopeStatus:
        runtime = self._require_runtime(device_id)
        if runtime.state is not ScopeSessionState.LIVE:
            raise ScopeServiceError(f"scope session is not LIVE for {device_id}")
        runtime.state = ScopeSessionState.HOLD
        if runtime.live_event is not None:
            runtime.live_event.clear()
        return self.status(device_id)

    def live(self, device_id: str) -> ScopeStatus:
        runtime = self._require_runtime(device_id)
        if runtime.state is not ScopeSessionState.HOLD:
            raise ScopeServiceError(f"scope session is not HOLD for {device_id}")
        runtime.state = ScopeSessionState.LIVE
        if runtime.live_event is not None:
            runtime.live_event.set()
        return self.status(device_id)

    async def stop(self, device_id: str) -> ScopeStatus:
        runtime = self._sessions.get(device_id)
        if runtime is None:
            return ScopeStatus(device_id, ScopeSessionState.DISCONNECTED, None, None)
        runtime.state = ScopeSessionState.DISCONNECTED
        if runtime.live_event is not None:
            runtime.live_event.set()

        cleanup_errors: list[str] = []
        task = runtime.task
        runtime.task = None
        if task is not None:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                cleanup_errors.append(f"task: {str(exc) or type(exc).__name__}")

        client = runtime.client
        runtime.client = None
        if client is not None:
            try:
                await client.close()
            except Exception as exc:
                cleanup_errors.append(f"transport: {str(exc) or type(exc).__name__}")

        if cleanup_errors:
            runtime.error = "; ".join(cleanup_errors)
            raise ScopeServiceError(f"scope cleanup failed for {device_id}: {runtime.error}")
        runtime.error = None
        return self.status(device_id)

    async def close(self) -> None:
        cleanup_errors: list[str] = []
        for device_id in tuple(self._sessions):
            try:
                await self.stop(device_id)
            except ScopeServiceError as exc:
                cleanup_errors.append(f"{device_id}: {exc}")
        if cleanup_errors:
            raise ScopeServiceError("scope cleanup failed: " + "; ".join(cleanup_errors))

    def _require_runtime(self, device_id: str) -> _Runtime:
        runtime = self._sessions.get(device_id)
        if runtime is None or runtime.state in {ScopeSessionState.DISCONNECTED, ScopeSessionState.ERROR}:
            raise ScopeServiceError(f"no controllable scope session for {device_id}")
        return runtime

    async def _run(self, runtime: _Runtime) -> None:
        loop = asyncio.get_running_loop()
        next_request_at = loop.time()
        try:
            while runtime.state not in {ScopeSessionState.DISCONNECTED, ScopeSessionState.ERROR}:
                event = runtime.live_event
                if event is None:
                    return
                await event.wait()
                if runtime.state is not ScopeSessionState.LIVE:
                    continue
                wait_s = next_request_at - loop.time()
                if wait_s > 0:
                    await asyncio.sleep(wait_s)
                if runtime.state is not ScopeSessionState.LIVE:
                    continue
                request_started = loop.time()
                runtime.sequence += 1
                client = runtime.client
                if client is None:
                    raise ScopeServiceError("scope transport is unavailable")
                try:
                    capture = await client.capture_once(
                        sequence=runtime.sequence,
                        listen_s=self._listen_s,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    runtime.state = ScopeSessionState.ERROR
                    runtime.error = str(exc) or type(exc).__name__
                    event.clear()
                    try:
                        await client.close()
                    except Exception as close_exc:
                        close_error = str(close_exc) or type(close_exc).__name__
                        runtime.error = f"{runtime.error}; cleanup failed: {close_error}"
                    finally:
                        if runtime.client is client:
                            runtime.client = None
                    return
                runtime.capture = capture
                next_request_at = request_started + self._interval_s
        except asyncio.CancelledError:
            raise
