"""Geographic source selection and cache invalidation behavior."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock

import pytest
from backend.station_catalog import StationCatalog
from backend.weather_query import QueryClarificationError, RequestedPoint
from weather_fixtures import POINT, STATION


def test_repeated_and_concurrent_questions_share_one_catalog_read():
    """Concurrent requests must not trigger repeated scans of weather indexes."""
    load = Mock(return_value=[STATION])
    catalog = StationCatalog(load)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(catalog.resolve, [POINT] * 20)) == [STATION] * 20
    load.assert_called_once()


def test_expiry_reloads_and_failed_refresh_never_serves_stale_sources():
    """Refresh errors propagate and remain retryable instead of caching stale data."""
    clock = Mock(return_value=0)
    load = Mock(side_effect=[[STATION], RuntimeError("database down"), [replace(STATION, id="2")]])
    catalog = StationCatalog(load, ttl=10, clock=clock)
    assert catalog.resolve(POINT).id == "1"
    clock.return_value = 11
    with pytest.raises(RuntimeError):
        catalog.resolve(POINT)
    assert catalog.resolve(POINT).id == "2"
    assert load.call_count == 3


def test_empty_catalog_recovers_on_next_request():
    """Indexing new records is visible immediately after an empty catalog."""
    catalog = StationCatalog(Mock(side_effect=[[], [STATION]]))
    with pytest.raises(QueryClarificationError):
        catalog.resolve(POINT)
    assert catalog.resolve(POINT) == STATION


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": None},
        {"longitude": "nan"},
        {"longitude": "invalid"},
        {"longitude": "0"},
        {"state": "OR"},
        {"latitude": "90"},
        {"id": "invalid"},
        {"name": ""},
    ],
)
def test_invalid_coordinates_and_identities_cannot_be_selected(change):
    """Keep malformed or unsupported source records out of location selection."""
    catalog = StationCatalog(lambda: [replace(STATION, **change)])
    with pytest.raises(QueryClarificationError):
        catalog.resolve(POINT)


@pytest.mark.parametrize("change", [{"name": "Other"}, {"county": "Other"}, {"latitude": "46.8"}])
def test_conflicting_versions_of_one_station_are_not_selected(change):
    """A reused ID cannot silently refer to different places."""
    catalog = StationCatalog(lambda: [STATION, replace(STATION, **change)])
    with pytest.raises(QueryClarificationError):
        catalog.resolve(POINT)


def test_nearest_source_and_distance_limit():
    """Distance chooses the nearby identity and remote points require clarification."""
    further = replace(STATION, id="2", latitude="46.8")
    catalog = StationCatalog(lambda: [further, STATION])
    assert catalog.resolve(POINT).id == "1"
    with pytest.raises(QueryClarificationError, match="50 km"):
        catalog.resolve(RequestedPoint(latitude=0, longitude=0))


def test_signed_and_west_positive_longitudes_are_the_same_source():
    """Normalize only source coordinates; user longitudes keep their sign."""
    catalog = StationCatalog(lambda: [STATION, replace(STATION, longitude="-117.181")])
    assert catalog.resolve(POINT).id == "1"
    with pytest.raises(QueryClarificationError):
        catalog.resolve(RequestedPoint(latitude=POINT.latitude, longitude=117.18))
