from emonio_viewer.diagnostics.metrics import DeviceMetrics


def test_metrics_keep_latency_and_error_counts() -> None:
    metrics = DeviceMetrics()
    metrics.record_valid_cycle(100.0, 0.2)
    metrics.record_valid_cycle(200.0, 0.1)
    metrics.record_timeout()
    snapshot = metrics.snapshot()
    assert snapshot.cycles_total == 3
    assert snapshot.valid_cycles == 2
    assert snapshot.invalid_cycles == 1
    assert snapshot.timeouts == 1
    assert snapshot.mean_latency_ms == 150.0
    assert snapshot.max_latency_ms == 200.0


def test_reconnect_count_is_connections_after_first() -> None:
    metrics = DeviceMetrics()
    metrics.set_connections_opened(1)
    assert metrics.snapshot().reconnects == 0
    metrics.set_connections_opened(3)
    assert metrics.snapshot().reconnects == 2
