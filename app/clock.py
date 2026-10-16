"""Time source for the service.

Business logic never reads the wall clock directly. It asks the injected
:class:`Clock`, so tests can pin time with :class:`FixedClock` and move it
forward explicitly.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that can tell the current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...

    def today(self) -> date:
        """Return the current UTC calendar date."""
        ...


class SystemClock:
    """The real clock, in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, start: datetime) -> None:
        self._now = _as_utc(start)

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> None:
        """Move the clock forward. Moving backwards is not allowed."""
        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta < timedelta(0):
            raise ValueError("FixedClock cannot move backwards")
        self._now += delta

    def set(self, moment: datetime) -> None:
        """Jump to an exact moment (forwards or backwards)."""
        self._now = _as_utc(moment)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("expected a timezone-aware datetime")
    return moment.astimezone(UTC)
