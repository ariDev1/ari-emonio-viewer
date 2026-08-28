class FixedDeadlineScheduler:
    """Generate fixed monotonic deadlines without completion-time drift."""

    def __init__(self, interval_s: float, first_deadline: float) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        self.interval_s = interval_s
        self._next = first_deadline

    def consume_deadline(self) -> float:
        current = self._next
        self._next += self.interval_s
        return current
