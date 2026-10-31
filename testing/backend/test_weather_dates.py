"""The interpretation boundary validates calendar values without parsing prose."""

import pytest
from backend.weather_intent import WeatherIntent
from pydantic import ValidationError
from weather_fixtures import STATION, intent_json


@pytest.mark.parametrize(
    "start,end",
    [
        ("2024-02-29", "2024-03-01"),
        ("2025-12-31", "2026-01-01"),
        ("2026-09-09", "2026-09-09"),
    ],
)
def test_valid_periods_preserve_exact_dates(start, end):
    """Keep leap days and year boundaries exactly as interpreted."""
    query = WeatherIntent.model_validate_json(intent_json(start=start, end=end)).selection(STATION)
    assert query.start.isoformat() == start
    assert query.end.isoformat() == end
    assert query.station_ids == (STATION.id,)


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-02-30"},
        {"start": "2026-09-10", "end": "2026-09-09"},
        {"start": None},
        {"end": None},
        {"start": "09/09/2026"},
        {"start": 1788912000},
        {"start": "2026-09-09 12:00:00"},
        {"question": " "},
        {"station_ids": ["99"]},
    ],
)
def test_malformed_model_dates_and_generated_ids_cannot_execute(changes):
    """Invalid structured output is a provider error, never a broader query."""
    with pytest.raises(ValidationError):
        WeatherIntent.model_validate_json(intent_json(**changes))
