"""Calendar date bounds for weather retrieval."""

from datetime import date

import pytest
from backend.weather_query import MissingDateError, QueryClarificationError, _dates

TODAY = date(2026, 9, 11)


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("2026-09-09", "2026-09-09", "2026-09-09"),
        ("September 9, 2026", "2026-09-09", "2026-09-09"),
        ("Sep. 9th", "2026-09-09", "2026-09-09"),
        ("yesterday", "2026-09-10", "2026-09-10"),
        ("today", "2026-09-11", "2026-09-11"),
        ("tomorrow", "2026-09-12", "2026-09-12"),
        ("last week", "2026-08-31", "2026-09-06"),
        ("this week", "2026-09-07", "2026-09-11"),
        ("last month", "2026-08-01", "2026-08-31"),
        ("this month", "2026-09-01", "2026-09-11"),
        ("past 7 days", "2026-09-04", "2026-09-10"),
        ("3 days ago", "2026-09-08", "2026-09-08"),
        ("from 2026-09-01 to 2026-09-09", "2026-09-01", "2026-09-09"),
        ("between September 1, 2026 and September 9, 2026", "2026-09-01", "2026-09-09"),
    ],
)
def test_resolves_date_bounds(period: str, start: str, end: str) -> None:
    """Resolve inclusive dates using an explicit clock."""
    actual_start, actual_end = _dates(f"Pullman temperature {period}", TODAY)
    assert actual_start.isoformat() == start
    assert actual_end.isoformat() == end


@pytest.mark.parametrize(
    "period",
    [
        "on 2026-02-30",
        "from 2026-09-09 to 2026-09-01",
        "on 2026-09-09 and 2026-09-11",
        "on September 9 and 12",
        "on September 9 last year",
        "last 0 days",
        "past 999999 days",
        "on 2026-09-09 yesterday",
        "yesterday in 2025",
        "on 9/10/2026",
        "on September 9, 2025 to September 10",
        "today and yesterday",
        "2026-09-01 to 2026-09-02 to 2026-09-03",
    ],
)
def test_invalid_or_ambiguous_dates_require_clarification(period: str) -> None:
    """Do not retrieve a different period by dropping part of the request."""
    with pytest.raises(QueryClarificationError):
        _dates(f"Pullman temperature {period}", TODAY)


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 1, 1), date(2025, 12, 31)), (date(2024, 3, 1), date(2024, 2, 29))],
)
def test_yesterday_crosses_year_and_leap_day(today: date, expected: date) -> None:
    """Calendar arithmetic handles year boundaries and leap days."""
    assert _dates("Pullman yesterday", today) == (expected, expected)


def test_missing_date_requires_clarification() -> None:
    """A question without a date must not silently become today's weather."""
    with pytest.raises(MissingDateError):
        _dates("Pullman temperature", TODAY)
