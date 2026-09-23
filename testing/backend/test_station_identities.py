"""Tests for indexed station identities."""

from unittest.mock import MagicMock

import pytest
from backend.vector_store import PgVectorStore
from backend.weather_query import Station
from pytest import MonkeyPatch


@pytest.mark.parametrize("table", ["daily_index", "live_index", "forecast_index"])
def test_station_reads_preserve_identity(monkeypatch: MonkeyPatch, table: str) -> None:
    """Keep distinct station IDs, including names shared by different counties."""
    connection, embedding = MagicMock(), MagicMock()
    connection.simple_query.side_effect = [
        [(101, "Pullman", "Whitman"), ("102", "Pullman", "Douglas"), ("103", "Colfax", None)],
        [],
    ]
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", lambda: connection)
    store = PgVectorStore(embedding, table=table)

    assert store.stations() == [
        Station("101", "Pullman", "Whitman"),
        Station("102", "Pullman", "Douglas"),
        Station("103", "Colfax", ""),
    ]
    assert store.stations() == []
    embedding.embed_document.assert_not_called()
    embedding.embed_documents.assert_not_called()


def test_station_read_recovers_after_failure(monkeypatch: MonkeyPatch) -> None:
    """Propagate a failed read and query again on the next request."""
    connection, embedding = MagicMock(), MagicMock()
    connection.simple_query.side_effect = [RuntimeError("database unavailable"), [("1", "Pullman", "Whitman")]]
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", lambda: connection)
    store = PgVectorStore(embedding)

    with pytest.raises(RuntimeError, match="database unavailable"):
        store.stations()
    assert store.stations() == [Station("1", "Pullman", "Whitman")]
    embedding.embed_document.assert_not_called()
