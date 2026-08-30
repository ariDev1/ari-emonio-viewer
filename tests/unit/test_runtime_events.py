from datetime import datetime, timezone

from emonio_viewer.runtime.events import DiagnosticEvent, RuntimeEventBus, Severity


def diagnostic(device_id: str, cycle_id: int) -> DiagnosticEvent:
    return DiagnosticEvent(
        device_id=device_id,
        cycle_id=cycle_id,
        occurred_utc=datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc),
        event="TEST_EVENT",
        severity=Severity.INFO,
        detail="test",
    )


def test_event_bus_counts_dropped_deliveries_by_device_without_blocking() -> None:
    bus = RuntimeEventBus()
    subscriber = bus.subscribe(maxsize=1)

    bus.publish(diagnostic("meter-a", 1))
    bus.publish(diagnostic("meter-a", 2))
    bus.publish(diagnostic("meter-b", 3))

    assert subscriber.get_nowait().cycle_id == 3
    assert bus.dropped_deliveries("meter-a") == 2
    assert bus.dropped_deliveries("meter-b") == 0
    assert bus.dropped_deliveries() == 2


def test_event_bus_counts_deliveries_not_unique_events() -> None:
    bus = RuntimeEventBus()
    first = bus.subscribe(maxsize=1)
    second = bus.subscribe(maxsize=1)

    bus.publish(diagnostic("meter-a", 1))
    bus.publish(diagnostic("meter-a", 2))

    assert first.get_nowait().cycle_id == 2
    assert second.get_nowait().cycle_id == 2
    assert bus.dropped_deliveries("meter-a") == 2
    assert bus.dropped_deliveries() == 2
