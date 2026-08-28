from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from emonio_viewer.scope.client import ScopeClientError
from emonio_viewer.scope.model import ScopeCapture, ScopeSessionState
from emonio_viewer.scope.service import ScopeService, ScopeServiceError, ScopeSessionConflict


def _capture(sequence: int) -> ScopeCapture:
    from emonio_viewer.scope.protocol import build_capture, decode_binary_frame, decode_metadata, FIELD_SAMPLE_COUNT
    import json
    import struct

    channels = {}
    for channel in range(6):
        payload = b"\xe5\xd2\x00" + bytes([channel]) + struct.pack(
            f"<{FIELD_SAMPLE_COUNT}f", *([float(channel)] * FIELD_SAMPLE_COUNT)
        )
        channels[channel] = decode_binary_frame(payload)
    metadata = {}
    for phase in range(3):
        metadata[phase] = decode_metadata(
            json.dumps(
                {
                    "type": "scope",
                    "phase": phase,
                    "connected": 1,
                    "vrms": 230.0,
                    "irms": 10.0,
                    "freq": 50.0,
                    "pf": 0.1,
                    "ms": 35.6,
                }
            )
        )
    return build_capture(
        sequence=sequence,
        received_utc=f"2026-08-28T10:00:{sequence:02d}+00:00",
        channels=channels,
        metadata=metadata,
        channel_order=(0, 1, 2, 3, 4, 5),
        metadata_order=(0, 1, 2),
    )


class FakeClient:
    def __init__(self, device: str, *, fail_after: int | None = None) -> None:
        self.device = device
        self.calls = 0
        self.closed = False
        self.fail_after = fail_after

    async def capture_once(self, *, sequence: int, listen_s: float = 2.0):
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise ScopeClientError("incomplete scope capture")
        return _capture(sequence)

    async def close(self):
        self.closed = True


async def _wait_until(predicate, timeout: float = 0.5) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.002)


def test_scope_service_keeps_live_state_and_captures_isolated_per_device() -> None:
    async def exercise():
        clients = {}

        async def factory(host, username, password):
            client = FakeClient(host)
            clients[host] = client
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("a", "host-a", "user-a", "pass-a")
        await service.start("b", "host-b", "user-b", "pass-b")
        await _wait_until(lambda: clients["host-a"].calls >= 2 and clients["host-b"].calls >= 2)
        a = service.status("a")
        b = service.status("b")
        await service.close()
        return a, b, clients

    a, b, clients = asyncio.run(exercise())
    assert a.state is ScopeSessionState.LIVE
    assert b.state is ScopeSessionState.LIVE
    assert a.capture is not None and a.capture.sequence >= 2
    assert b.capture is not None and b.capture.sequence >= 2
    assert clients["host-a"].closed is True
    assert clients["host-b"].closed is True


def test_hold_stops_new_requests_and_live_resumes_without_new_credentials() -> None:
    async def exercise():
        client = FakeClient("host")

        async def factory(_host, _username, _password):
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("a", "host", "user", "pass")
        await _wait_until(lambda: client.calls >= 2)
        service.hold("a")
        await asyncio.sleep(0.03)
        held_calls = client.calls
        held = service.status("a")
        await asyncio.sleep(0.03)
        assert client.calls == held_calls
        service.live("a")
        await _wait_until(lambda: client.calls > held_calls)
        resumed = service.status("a")
        await service.close()
        return held, resumed

    held, resumed = asyncio.run(exercise())
    assert held.state is ScopeSessionState.HOLD
    assert resumed.state is ScopeSessionState.LIVE


def test_stop_closes_transport_and_preserves_latest_capture_as_volatile_evidence() -> None:
    async def exercise():
        client = FakeClient("host")

        async def factory(_host, _username, _password):
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("a", "host", "user", "pass")
        await _wait_until(lambda: client.calls >= 1)
        before = service.status("a").capture
        await service.stop("a")
        after = service.status("a")
        await service.close()
        return before, after, client.closed

    before, after, closed = asyncio.run(exercise())
    assert before is not None
    assert after.state is ScopeSessionState.DISCONNECTED
    assert after.capture == before
    assert closed is True


def test_capture_failure_fails_closed_and_sends_no_later_requests() -> None:
    async def exercise():
        client = FakeClient("host", fail_after=2)

        async def factory(_host, _username, _password):
            return client

        service = ScopeService(client_factory=factory, interval_s=0.005)
        await service.start("a", "host", "user", "pass")
        await _wait_until(lambda: service.status("a").state is ScopeSessionState.ERROR)
        failed_calls = client.calls
        await asyncio.sleep(0.03)
        status = service.status("a")
        await service.close()
        return failed_calls, client.calls, status, client.closed

    first_count, later_count, status, closed = asyncio.run(exercise())
    assert first_count == 2
    assert later_count == 2
    assert status.state is ScopeSessionState.ERROR
    assert "incomplete scope capture" in (status.error or "")
    assert closed is True


def test_duplicate_start_is_rejected_until_session_is_stopped() -> None:
    async def exercise():
        client = FakeClient("host")

        async def factory(_host, _username, _password):
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("a", "host", "user", "pass")
        with pytest.raises(ScopeSessionConflict):
            await service.start("a", "host", "user", "pass")
        await service.stop("a")
        await service.close()

    asyncio.run(exercise())


def test_scope_service_reports_only_controllable_active_owners_in_device_order() -> None:
    async def exercise():
        clients = {}

        async def factory(host, _username, _password):
            client = FakeClient(host)
            clients[host] = client
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("b", "host-b", "user-b", "pass-b")
        await service.start("a", "host-a", "user-a", "pass-a")
        await _wait_until(lambda: clients["host-a"].calls >= 1 and clients["host-b"].calls >= 1)
        service.hold("b")
        before_stop = service.active_statuses()
        await service.stop("a")
        after_stop = service.active_statuses()
        await service.close()
        return before_stop, after_stop

    before_stop, after_stop = asyncio.run(exercise())
    assert [(status.device_id, status.state.value) for status in before_stop] == [
        ("a", "LIVE"),
        ("b", "HOLD"),
    ]
    assert [(status.device_id, status.state.value) for status in after_stop] == [
        ("b", "HOLD"),
    ]


def test_stop_during_connecting_prevents_pending_start_from_reaching_live() -> None:
    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        client = FakeClient("host")

        async def factory(_host, _username, _password):
            entered.set()
            await release.wait()
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        start_task = asyncio.create_task(service.start("a", "host", "user", "pass"))
        await entered.wait()
        assert service.status("a").state is ScopeSessionState.CONNECTING

        stopped = await service.stop("a")
        release.set()
        with pytest.raises(ScopeServiceError) as exc_info:
            await start_task
        await asyncio.sleep(0)

        final = service.status("a")
        return stopped, final, client, exc_info.value, service.active_statuses()

    stopped, final, client, error, active = asyncio.run(exercise())
    assert stopped.state is ScopeSessionState.DISCONNECTED
    assert final.state is ScopeSessionState.DISCONNECTED
    assert client.closed is True
    assert client.calls == 0
    assert active == ()
    assert "cancel" in str(error).lower()


def test_old_connecting_start_cannot_take_ownership_from_new_start() -> None:
    async def exercise():
        first_entered = asyncio.Event()
        first_release = asyncio.Event()
        first_client = FakeClient("first")
        second_client = FakeClient("second")
        calls = 0

        async def factory(_host, _username, _password):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_entered.set()
                await first_release.wait()
                return first_client
            return second_client

        service = ScopeService(client_factory=factory, interval_s=10.0)
        first_start = asyncio.create_task(service.start("a", "host", "user", "pass"))
        await first_entered.wait()
        await service.stop("a")

        second_status = await service.start("a", "host", "user", "pass")
        first_release.set()
        with pytest.raises(ScopeServiceError) as exc_info:
            await first_start
        await _wait_until(lambda: second_client.calls >= 1)
        final = service.status("a")
        await service.close()
        return second_status, final, first_client, second_client, exc_info.value

    second_status, final, first_client, second_client, error = asyncio.run(exercise())
    assert second_status.state is ScopeSessionState.LIVE
    assert final.state is ScopeSessionState.LIVE
    assert first_client.closed is True
    assert first_client.calls == 0
    assert second_client.calls >= 1
    assert second_client.closed is True
    assert "cancel" in str(error).lower()


def test_stop_during_connecting_is_not_overwritten_by_late_connect_failure() -> None:
    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def factory(_host, _username, _password):
            entered.set()
            await release.wait()
            raise RuntimeError("late connection failure")

        service = ScopeService(client_factory=factory, interval_s=0.01)
        start_task = asyncio.create_task(service.start("a", "host", "user", "pass"))
        await entered.wait()
        stopped = await service.stop("a")
        release.set()
        with pytest.raises(ScopeServiceError) as exc_info:
            await start_task
        return stopped, service.status("a"), exc_info.value

    stopped, final, error = asyncio.run(exercise())
    assert stopped.state is ScopeSessionState.DISCONNECTED
    assert final.state is ScopeSessionState.DISCONNECTED
    assert "cancel" in str(error).lower()
    assert "late connection failure" not in str(error)


def test_close_attempts_every_scope_session_before_reporting_cleanup_failure() -> None:
    class CloseFailClient(FakeClient):
        def __init__(self, device: str, *, fail_close: bool = False) -> None:
            super().__init__(device)
            self.close_calls = 0
            self.fail_close = fail_close

        async def close(self):
            self.close_calls += 1
            self.closed = True
            if self.fail_close:
                raise RuntimeError(f"close failed for {self.device}")

    async def exercise():
        clients = {
            "host-a": CloseFailClient("a", fail_close=True),
            "host-b": CloseFailClient("b"),
        }

        async def factory(host, _username, _password):
            return clients[host]

        service = ScopeService(client_factory=factory, interval_s=10.0)
        await service.start("a", "host-a", "user-a", "pass-a")
        await service.start("b", "host-b", "user-b", "pass-b")
        await _wait_until(lambda: clients["host-a"].calls >= 1 and clients["host-b"].calls >= 1)
        with pytest.raises(ScopeServiceError) as exc_info:
            await service.close()
        return clients, service.status("a"), service.status("b"), str(exc_info.value)

    clients, a, b, message = asyncio.run(exercise())
    assert clients["host-a"].close_calls == 1
    assert clients["host-b"].close_calls == 1
    assert clients["host-b"].closed is True
    assert a.state is ScopeSessionState.DISCONNECTED
    assert b.state is ScopeSessionState.DISCONNECTED
    assert "a" in message
    assert "close failed for a" in message


def test_capture_error_preserves_primary_error_when_transport_close_also_fails() -> None:
    class CaptureAndCloseFailClient(FakeClient):
        async def capture_once(self, *, sequence: int, listen_s: float = 2.0):
            self.calls += 1
            raise ScopeClientError("capture failed")

        async def close(self):
            self.closed = True
            raise RuntimeError("transport close failed")

    async def exercise():
        client = CaptureAndCloseFailClient("host")

        async def factory(_host, _username, _password):
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        await service.start("a", "host", "user", "pass")
        await _wait_until(lambda: service.status("a").state is ScopeSessionState.ERROR)
        await asyncio.sleep(0)
        runtime = service._sessions["a"]
        task = runtime.task
        assert task is not None and task.done()
        task_error = task.exception()
        return service.status("a"), runtime.client, client.closed, task_error

    status, runtime_client, closed, task_error = asyncio.run(exercise())
    assert status.state is ScopeSessionState.ERROR
    assert status.error is not None and status.error.startswith("capture failed")
    assert "transport close failed" in status.error
    assert runtime_client is None
    assert closed is True
    assert task_error is None


def test_cancelled_connecting_start_preserves_cancellation_when_late_client_close_fails() -> None:
    class CloseFailClient(FakeClient):
        async def close(self):
            self.closed = True
            raise RuntimeError("late transport close failed")

    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        client = CloseFailClient("host")

        async def factory(_host, _username, _password):
            entered.set()
            await release.wait()
            return client

        service = ScopeService(client_factory=factory, interval_s=0.01)
        start_task = asyncio.create_task(service.start("a", "host", "user", "pass"))
        await entered.wait()
        await service.stop("a")
        release.set()
        with pytest.raises(ScopeServiceError) as exc_info:
            await start_task
        return service.status("a"), client.closed, str(exc_info.value)

    status, closed, message = asyncio.run(exercise())
    assert status.state is ScopeSessionState.DISCONNECTED
    assert closed is True
    assert "start cancelled" in message
    assert "late transport close failed" in message
