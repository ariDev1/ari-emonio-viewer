from emonio_viewer.acquisition.scheduler import FixedDeadlineScheduler


def test_next_deadline_is_based_on_planned_time_not_completion_time() -> None:
    scheduler = FixedDeadlineScheduler(interval_s=2.0, first_deadline=100.0)
    assert scheduler.consume_deadline() == 100.0
    assert scheduler.consume_deadline() == 102.0
    assert scheduler.consume_deadline() == 104.0
