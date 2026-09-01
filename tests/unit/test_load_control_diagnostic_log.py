from datetime import datetime, timezone
from pathlib import Path


def _diagnostic_types():
    path = Path("src/emonio_viewer/load_control/diagnostic_log.py")
    assert path.is_file(), "Stage-2 diagnostic log module is not implemented"
    from emonio_viewer.load_control.diagnostic_log import LoadControlDiagnosticLog

    return LoadControlDiagnosticLog


def test_diagnostic_log_formats_backend_owned_copyable_lines() -> None:
    LoadControlDiagnosticLog = _diagnostic_types()
    fixed = datetime(2026, 9, 1, 16, 32, 1, 524000, tzinfo=timezone.utc)
    log = LoadControlDiagnosticLog(max_events=10, utc_now=lambda: fixed)

    event = log.append(
        "HELLO_QUALIFIED",
        protocol=1,
        device_class="ARI_LOAD_ACTUATOR",
        capability="ACTIVE_LOAD_CONTROL",
    )

    assert event.sequence == 1
    assert event.utc == "2026-09-01T16:32:01.524Z"
    assert event.event == "HELLO_QUALIFIED"
    assert event.line == (
        '2026-09-01T16:32:01.524Z  HELLO_QUALIFIED '
        'protocol=1 device_class="ARI_LOAD_ACTUATOR" '
        'capability="ACTIVE_LOAD_CONTROL"'
    )
    assert log.latest_sequence == 1
    assert log.recent() == (event,)


def test_diagnostic_log_is_bounded_and_supports_clear_view_cursor() -> None:
    LoadControlDiagnosticLog = _diagnostic_types()
    fixed = datetime(2026, 9, 1, 16, 32, 1, tzinfo=timezone.utc)
    log = LoadControlDiagnosticLog(max_events=2, utc_now=lambda: fixed)

    first = log.append("LAN_SCAN_STARTED")
    second = log.append("LAN_SCAN_COMPLETE", count=0)
    third = log.append("LAN_SCAN_STARTED")

    assert first.sequence == 1
    assert second.sequence == 2
    assert third.sequence == 3
    assert tuple(event.sequence for event in log.recent()) == (2, 3)
    assert tuple(event.sequence for event in log.recent(after_sequence=2)) == (3,)
    assert log.latest_sequence == 3
