"""Station repositories share the existing database connection."""

from unittest.mock import MagicMock

import pytest
from backend.vector_store import PgVectorStore
from weather_fixtures import POINT


@pytest.mark.parametrize("table", ["daily_index", "live_index", "forecast_index"])
def test_lookup_reuses_connection_and_restricts_record_availability(monkeypatch, table):
    """A repository for one store cannot select a station found only in another store."""
    connection, embedding = MagicMock(), MagicMock()
    connection.simple_query.return_value = [("1", "Pullman", "Whitman", 46.731, -117.181, "WA")]
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", factory)
    store = PgVectorStore(embedding, table=table)
    assert store.station_catalog().resolve(POINT).id == "1"
    factory.assert_called_once()
    query = connection.simple_query.call_args.args[0].decode()
    assert f"FROM {table} WHERE metadata->>'id' = s.station_id" in query
    for other in {"daily_index", "live_index", "forecast_index"} - {table}:
        assert f"FROM {other}" not in query
    embedding.embed_document.assert_not_called()
    embedding.embed_documents.assert_not_called()
