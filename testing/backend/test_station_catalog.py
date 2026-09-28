"""Station catalog reuse and refresh behavior."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest
from backend.retriever import NO_DATA, Retriever
from backend.station_catalog import StationCatalog
from backend.vector_store import PgVectorStore
from backend.weather_query import Station

STATION = Station("1", "Pullman", "Whitman")


def test_concurrent_requests_share_one_catalog_load():
    """Requests arriving together reuse the same metadata read."""
    load = Mock(return_value=[STATION])
    catalog = StationCatalog(load)
    start = Barrier(8)

    def read_catalog():
        start.wait(timeout=5)
        return catalog.stations()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [pool.submit(read_catalog) for _ in range(8)]
        assert [result.result(timeout=5) for result in results] == [[STATION]] * 8
    load.assert_called_once()


def test_catalog_refreshes_when_its_lifetime_expires():
    """Refresh at five minutes and preserve the cached snapshot before then."""
    clock = Mock(return_value=0)
    replacement = Station("2", "Pullman East", "Whitman")
    load = Mock(side_effect=[[STATION], [replacement]])
    catalog = StationCatalog(load, clock=clock)
    assert catalog.stations() == [STATION]
    clock.return_value = 299
    assert catalog.stations() == [STATION]
    load.assert_called_once()
    clock.return_value = 300
    assert catalog.stations() == [replacement]
    assert load.call_count == 2


def test_failed_refresh_retries_without_serving_expired_data():
    """A database error leaves refresh retryable on the next request."""
    clock = Mock(return_value=0)
    replacement = Station("2", "Pullman East", "Whitman")
    load = Mock(side_effect=[[STATION], RuntimeError("database unavailable"), [replacement]])
    catalog = StationCatalog(load, clock=clock)
    assert catalog.stations() == [STATION]
    clock.return_value = 300
    with pytest.raises(RuntimeError, match="database unavailable"):
        catalog.stations()
    assert catalog.stations() == [replacement]
    assert load.call_count == 3


def test_empty_catalog_retries_on_the_next_request():
    """An initially empty index can become available without waiting five minutes."""
    load = Mock(side_effect=[[], [STATION]])
    catalog = StationCatalog(load)
    assert catalog.stations() == []
    assert catalog.stations() == [STATION]
    assert load.call_count == 2


def test_duplicate_identities_are_cached_without_exposing_mutable_state():
    """Duplicate rows and mutations of a returned list cannot alter the cache."""
    load = Mock(return_value=[STATION, STATION])
    catalog = StationCatalog(load)
    returned = catalog.stations()
    assert returned == [STATION]
    returned.clear()
    assert catalog.stations() == [STATION]
    load.assert_called_once()


def test_repeated_questions_reuse_metadata_from_all_stores():
    """The retriever caches identities while continuing to search current records."""
    stores = [MagicMock(spec=PgVectorStore), MagicMock(spec=PgVectorStore)]
    for store in stores:
        store.stations.return_value = [STATION]
        store.similarity_search.return_value = []
    retriever = Retriever(cast(list[PgVectorStore], stores), MagicMock())
    question = "Temperature at Pullman on 2026-09-09?"
    assert retriever.retrieve(question) == NO_DATA
    assert retriever.retrieve(question) == NO_DATA
    for store in stores:
        store.stations.assert_called_once()
        assert store.similarity_search.call_count == 2
