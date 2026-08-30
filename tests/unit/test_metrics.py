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


def test_latency_statistics_use_bounded_explicit_rolling_window() -> None:
    metrics = DeviceMetrics()
    window_size = 4096
    total = window_size + 2
    for value in range(total):
        metrics.record_valid_cycle(float(value), 0.0)

    snapshot = metrics.snapshot()

    assert snapshot.valid_cycles == total
    assert snapshot.latency_statistics_scope == "ROLLING_VALID_CYCLES"
    assert snapshot.latency_window_capacity == window_size
    assert snapshot.latency_window_samples == window_size
    assert snapshot.min_latency_ms == 2.0
    assert snapshot.max_latency_ms == float(total - 1)

    retained = list(range(2, total))
    rank = max(0, __import__("math").ceil(0.95 * len(retained)) - 1)
    assert snapshot.p95_latency_ms == float(retained[rank])


def test_latency_window_does_not_grow_after_capacity() -> None:
    metrics = DeviceMetrics()
    window_size = 4096
    for value in range(window_size * 3):
        metrics.record_valid_cycle(float(value), 0.0)

    assert len(metrics._latencies) == window_size
