"""Opt in PostgreSQL checks using temporary tables only."""

import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
from backend.vector_store import PgVectorStore
from backend.weather_query import WeatherQuery
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Set RUN_PGVECTOR_TESTS=1 for local PostgreSQL checks"
)


@pytest.fixture
def connection(database):
    """Create weather fixtures inside the disposable conversation test schema."""
    with database() as conn:
        for table in ("daily_index", "live_index", "forecast_index"):
            conn.execute(f"CREATE TABLE {table} (document text, metadata jsonb, embedding vector(3))")
        conn.execute(
            "CREATE INDEX daily_index_station_date_idx ON daily_index ((metadata->>'id'), (metadata->>'date'))"
        )
        migration = Path(__file__).parents[2] / "deployment/migrations/001_station_search_indexes.sql"
        conn.execute(migration.read_bytes())
        yield conn


@pytest.mark.parametrize("table", ["daily_index", "live_index", "forecast_index"])
def test_location_and_date_filter_before_limit_in_real_database(connection, monkeypatch, table):
    """A closer vector for another location or date must not displace the requested source."""
    connection.execute(
        f"INSERT INTO {table} SELECT 'unrelated', jsonb_build_object('id', n::text, 'date', '2026-09-09', "
        "'timestamp', '2026-09-09 12:00:00', 'dates', jsonb_build_array('2026-09-09')), '[0,0,0]'::vector "
        "FROM generate_series(2, 2000) n"
    )
    content = (
        "| forecast_time | temperature in F |\n| --- | --- |\n"
        "| 2026-09-09 12:00:00 | 72 |\n| 2026-09-10 12:00:00 | 85 |"
    )
    for day in ("2026-09-08", "2026-09-09"):
        metadata: dict[str, object] = {"id": "1", "station": "Pullman", "date": day, "timestamp": day + " 12:00:00"}
        if table == "forecast_index":
            metadata["dates"] = [day]
        connection.execute(f"INSERT INTO {table} VALUES (%s, %s, '[1,1,1]')", (content, Jsonb(metadata)))
    connection.execute(f"ANALYZE {table}")
    database, embedding = MagicMock(), MagicMock()
    database.simple_query.side_effect = lambda query, args: connection.execute(query, args).fetchall()
    embedding.embed_document.return_value = ([0.0, 0.0, 0.0], None)
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", lambda: database)
    store = PgVectorStore(embedding, table=table)
    result = store.similarity_search(
        "temperature", k=1, selection=WeatherQuery(("1",), date(2026, 9, 9), date(2026, 9, 9))
    )
    assert len(result) == 1 and result[0].metadata["id"] == "1"
    if table == "forecast_index":
        assert "2026-09-10" not in result[0].page_content
        assert "timestamp" not in result[0].metadata
    query, args = database.simple_query.call_args.args
    plan = connection.execute(b"EXPLAIN (FORMAT JSON) " + query, args).fetchone()[0]
    assert "Index" in str(plan), plan


def test_legacy_forecast_rows_and_full_precision_freshness(connection, monkeypatch):
    """Preserve older forecast indexes and match observation timestamps by day."""
    connection.execute(
        "INSERT INTO forecast_index VALUES (%s, %s, '[0,0,0]')",
        (
            "| forecast_time | temperature |\n| --- | --- |\n| 2026-09-09 12:00:00 | 72 |",
            Jsonb({"id": "1"}),
        ),
    )
    database, embedding = MagicMock(), MagicMock()
    database.simple_query.side_effect = lambda query, args: connection.execute(query, args).fetchall()
    embedding.embed_document.return_value = ([0.0, 0.0, 0.0], None)
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", lambda: database)
    result = PgVectorStore(embedding, table="forecast_index").similarity_search(
        "temperature",
        selection=WeatherQuery(("1",), date(2026, 9, 9), date(2026, 9, 9)),
    )
    assert result[0].metadata["dates"] == ["2026-09-09"]
    connection.execute(
        "INSERT INTO live_index VALUES ('reading', %s, '[0,0,0]')", (Jsonb({"timestamp": "2026-09-09 12:45:12"}),)
    )
    assert connection.execute(
        "SELECT EXISTS (SELECT 1 FROM live_index WHERE left(metadata->>'timestamp', 10) = %s)",
        ("2026-09-09",),
    ).fetchone()[0]


def test_shared_connection_recovers_after_a_failed_read(connection):
    """A failed lookup cannot leave later cached catalog refreshes in an aborted transaction."""
    from threading import Lock

    from backend.databases.pgvector import PgVectorConnection

    database = PgVectorConnection.__new__(PgVectorConnection)
    database.conn = connection
    database._query_lock = Lock()
    with pytest.raises(psycopg.Error):
        list(database.simple_query(b"SELECT missing_column FROM daily_index", ()))
    assert list(database.simple_query(b"SELECT 1", ())) == [(1,)]
