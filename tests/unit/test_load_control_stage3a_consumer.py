import asyncio
from queue import Empty

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.load_control.stage3a import Stage3ASafeCommandService
from emonio_viewer.runtime.events import RuntimeEventBus


class _UnusedChannel:
    def hello(self):
        return None


class _BoundedQueueProbe:
    def __init__(self, stop_sentinel) -> None:
        self._stop_sentinel = stop_sentinel
        self.calls: list[tuple[bool, float]] = []

    def get(self, block: bool, timeout: float):
        self.calls.append((block, timeout))
        if len(self.calls) == 1:
            raise Empty()
        return self._stop_sentinel


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        viewer=ViewerConfig(default_device="emonio-example"),
        recording=RecordingConfig(default_interval_s=1.0),
        devices=(
            DeviceConfig(
                id="emonio-example",
                name="Emonio Example",
                host="192.0.2.11",
                poll_interval_s=2.0,
                timeout_s=0.1,
            ),
        ),
    )


def test_stage3a_consumer_uses_bounded_queue_waits() -> None:
    async def scenario() -> None:
        service = Stage3ASafeCommandService(
            RuntimeEventBus(),
            _config(),
            _UnusedChannel(),
            viewer_session_id="VIEWER-STAGE3A-CONSUMER-TEST",
        )
        probe = _BoundedQueueProbe(service._stop_sentinel)
        service._subscriber = probe

        await asyncio.wait_for(service._consume_events(), timeout=0.5)

        assert len(probe.calls) == 2
        assert all(block is True for block, _timeout in probe.calls)
        assert all(0.0 < timeout <= 0.1 for _block, timeout in probe.calls)

    asyncio.run(scenario())
