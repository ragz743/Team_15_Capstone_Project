"""Validation of server selected locations and query bounds."""

from datetime import date, datetime

import pytest
from backend.weather_query import RequestedPoint, WeatherQuery
from pydantic import ValidationError


@pytest.mark.parametrize(
    "point",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": "46.7", "longitude": -117},
        {"latitude": float("nan"), "longitude": -117},
        {"latitude": 46.7, "longitude": float("inf")},
        {"latitude": 46.7, "longitude": -117, "station_id": "1"},
    ],
)
def test_invalid_points_are_rejected(point):
    """Reject malformed browser input without coercion or hidden station selection."""
    with pytest.raises(ValidationError):
        RequestedPoint.model_validate(point)


@pytest.mark.parametrize("ids", [(), ("",), ("1 OR true",), ("1", "")])
def test_query_requires_a_nonempty_valid_station_scope(ids):
    """No invalid identity can widen a weather search."""
    with pytest.raises(ValueError):
        WeatherQuery(ids, date(2026, 9, 1), date(2026, 9, 2))


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 9, 2), date(2026, 9, 1)),
        ("2026-09-01", date(2026, 9, 2)),
        (datetime(2026, 9, 1), date(2026, 9, 2)),
    ],
)
def test_query_rejects_invalid_periods(start, end):
    """Require ordered calendar dates before SQL construction."""
    with pytest.raises(ValueError):
        WeatherQuery(("1",), start, end)
