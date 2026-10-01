"""Point lookup without application catalog caching or broad metadata reads."""

import math
from unittest.mock import MagicMock

import pytest
from backend.station_catalog import StationCatalog, _search_bounds
from backend.weather_query import QueryClarificationError, RequestedPoint, Station
from weather_fixtures import POINT

ROW = ("1", "Pullman", "Whitman", 46.731, -117.181, "WA")


def test_resolve_returns_one_station_with_a_parameterized_geographic_query():
    """Pass the selected coordinates to the database and retrieve one source."""
    database = MagicMock()
    database.simple_query.return_value = [ROW]
    result = StationCatalog(database).resolve(POINT)
    assert result == Station("1", "Pullman", "Whitman", "46.731", "-117.181", "WA")
    query, values = database.simple_query.call_args.args
    assert b"FROM indexed_stations" in query
    assert b"s.location <@ box" in query and b"LIMIT 1" in query
    assert b"SELECT DISTINCT" not in query
    assert values[:3] == (POINT.latitude, POINT.longitude, 50)
    database.simple_query.assert_called_once()


def test_database_failures_propagate_and_the_next_request_retries():
    """Do not conceal query failures or return a cached source after a failure."""
    database = MagicMock()
    database.simple_query.side_effect = [[ROW], RuntimeError("database unavailable"), [ROW]]
    catalog = StationCatalog(database)
    assert catalog.resolve(POINT).id == "1"
    with pytest.raises(RuntimeError, match="database unavailable"):
        catalog.resolve(POINT)
    assert catalog.resolve(POINT).id == "1"
    assert database.simple_query.call_count == 3


def test_missing_source_is_not_cached():
    """Newly indexed stations become available on the next lookup."""
    database = MagicMock()
    database.simple_query.side_effect = [[], [ROW]]
    catalog = StationCatalog(database)
    with pytest.raises(QueryClarificationError, match="50 km"):
        catalog.resolve(POINT)
    assert catalog.resolve(POINT).id == "1"


@pytest.mark.parametrize("coordinates", [(0, 0), (90, 0), (-90, 0), (46.73, 117.18)])
def test_unsupported_points_skip_the_database(coordinates):
    """A search circle outside supported coordinates has no eligible source."""
    database = MagicMock()
    with pytest.raises(QueryClarificationError):
        StationCatalog(database).resolve(RequestedPoint(latitude=coordinates[0], longitude=coordinates[1]))
    database.simple_query.assert_not_called()


@pytest.mark.parametrize("radius", [0, -1, 101, float("nan"), float("inf")])
def test_invalid_radius_is_rejected(radius):
    """Reject invalid coverage limits before constructing a query."""
    with pytest.raises(ValueError, match="radius"):
        StationCatalog(MagicMock(), radius_km=radius)


def test_only_allowed_weather_indexes_can_enter_sql():
    """The table list comes from validated code rather than user supplied SQL."""
    with pytest.raises(ValueError, match="indexes"):
        StationCatalog(MagicMock(), tables=("daily_index; DROP TABLE indexed_stations",))
    with pytest.raises(ValueError, match="indexes"):
        StationCatalog(MagicMock(), tables=())


def test_bounding_box_encloses_the_search_circle():
    """Include the sphere's northern, southern and widest longitude extents."""
    bounds = _search_bounds(POINT, 50)
    assert bounds is not None
    west, south, east, north = bounds
    angle = 50 / 6371.0088
    for bearing in range(360):
        latitude, longitude, direction = map(math.radians, (POINT.latitude, POINT.longitude, bearing))
        target_latitude = math.asin(
            math.sin(latitude) * math.cos(angle) + math.cos(latitude) * math.sin(angle) * math.cos(direction)
        )
        target_longitude = longitude + math.atan2(
            math.sin(direction) * math.sin(angle) * math.cos(latitude),
            math.cos(angle) - math.sin(latitude) * math.sin(target_latitude),
        )
        assert south <= math.degrees(target_latitude) <= north
        assert west <= math.degrees(target_longitude) <= east
