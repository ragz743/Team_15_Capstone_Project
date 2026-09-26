"""Location and calendar interpretation for station/date retrieval."""

from datetime import date

import pytest
from backend.weather_query import (
    QueryClarificationError,
    Station,
    resolve_weather_query,
)

STATIONS = [
    Station("1", "Pullman", "Whitman"),
    Station("2", "Colfax", "Whitman"),
    Station("3", "Spokane", "Spokane"),
    Station("4", "Springfield East", "Douglas"),
    Station("5", "Springfield West", "Douglas"),
]
TODAY = date(2026, 9, 11)


@pytest.mark.parametrize(
    ("location", "ids"),
    [
        ("Pullman", ("1",)),
        ("pUlLmAn", ("1",)),
        ("station 2", ("2",)),
        ("Whitman County", ("1", "2")),
        ("Whitman", ("1", "2")),
        ("Spokane County", ("3",)),
    ],
)
def test_resolves_indexed_location(location: str, ids: tuple[str, ...]) -> None:
    """Use station IDs from the index, including county membership."""
    selection = resolve_weather_query(f"Temperature in {location} on 2026-09-09?", STATIONS, today=TODAY)
    assert selection.station_ids == ids
    assert selection.start == selection.end == date(2026, 9, 9)


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
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
    selection = resolve_weather_query(f"Pullman temperature {period}", STATIONS, today=TODAY)
    assert selection.start.isoformat() == start
    assert selection.end.isoformat() == end


@pytest.mark.parametrize(
    "question",
    [
        "Temperature yesterday?",
        "Temperature in Seattle yesterday?",
        "Pullman temperature recently?",
        "Temperature in Springfield yesterday?",
        "Temperature at station 999 yesterday?",
        "Pullman station 2 yesterday",
        "Pullman in Spokane County yesterday",
        "Temperature in Pullman and Seattle yesterday",
        "Seattle and Pullman yesterday",
        "station 1 and station 2 yesterday",
        "Pullman and Colfax yesterday",
        "Temperature in Pullman on 2026-02-30",
        "Pullman from 2026-09-09 to 2026-09-01",
        "Pullman on 2026-09-09 and 2026-09-11",
        "Pullman on September 9 and 12",
        "Pullman on September 9 last year",
        "Pullman before 2026-09-09",
        "Pullman yesterday at 3pm",
        "Pullman last 0 days",
        "Pullman past 999999 days",
        "Pullman on 2026-09-09 yesterday",
        "Not Pullman yesterday",
        "Pullman in Unknown County yesterday",
        "Pullman Adams County yesterday",
        "Pullman yesterday in 2025",
        "Pullman on 9/10/2026",
        "Pullman on September 9, 2025 to September 10",
        "Temperature in Pullman near Seattle yesterday",
    ],
)
def test_unclear_or_unsupported_questions_do_not_fall_back(question: str) -> None:
    """Require clarification instead of dropping a requested constraint."""
    with pytest.raises(QueryClarificationError):
        resolve_weather_query(question, STATIONS, today=TODAY)


def test_duplicate_station_names_require_id() -> None:
    """Do not arbitrarily choose between stations sharing an official name."""
    stations = [Station("1", "Pullman", "Whitman"), Station("2", "Pullman", "Douglas")]
    with pytest.raises(QueryClarificationError, match="station 1.*station 2"):
        resolve_weather_query("Pullman yesterday", stations, today=TODAY)
    assert resolve_weather_query("station 2 yesterday", stations, today=TODAY).station_ids == ("2",)
    assert resolve_weather_query("Pullman in Whitman County yesterday", stations, today=TODAY).station_ids == ("1",)
    assert resolve_weather_query("Pullman station 2 yesterday", stations, today=TODAY).station_ids == ("2",)


def test_relative_dates_cross_year_and_leap_day() -> None:
    """Calendar arithmetic must handle month and year boundaries."""
    assert resolve_weather_query("Pullman yesterday", STATIONS, today=date(2026, 1, 1)).start == date(2025, 12, 31)
    assert resolve_weather_query("Pullman yesterday", STATIONS, today=date(2024, 3, 1)).start == date(2024, 2, 29)


def test_longer_station_name_does_not_hide_a_separate_station() -> None:
    """Overlapping station names must distinguish one mention from two."""
    stations = [Station("1", "Pullman", "Whitman"), Station("2", "Pullman East", "Whitman")]
    assert resolve_weather_query("Pullman East yesterday", stations, today=TODAY).station_ids == ("2",)
    with pytest.raises(QueryClarificationError):
        resolve_weather_query("Pullman and Pullman East yesterday", stations, today=TODAY)


def test_units_do_not_hide_the_location() -> None:
    """Unit phrases and station phrases may appear in either order."""
    for question in (
        "Temperature in Fahrenheit at Pullman yesterday",
        "Temperature at Pullman in Fahrenheit yesterday",
    ):
        assert resolve_weather_query(question, STATIONS, today=TODAY).station_ids == ("1",)
