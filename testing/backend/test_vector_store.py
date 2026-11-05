"""Tests for backend.vector_store."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, cast

import pytest
from backend.models._embedding_base import _BaseEmbedding
from backend.vector_store import PgVectorStore
from backend.weather_query import WeatherQuery
from langchain_core.documents import Document


class FakeEmbedding(_BaseEmbedding):
    """Embedding test double."""

    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        """Return a deterministic query embedding."""
        return [0.1, 0.2, 0.3], document

    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        """Return deterministic document embeddings."""
        return [self.embed_document(document) for document in documents]


class FakePgVectorConnection:
    """PgVector connection test double."""

    last_instance: "FakePgVectorConnection | None" = None

    def __init__(self) -> None:
        """Create a fake pgvector connection."""
        self.query: bytes | None = None
        self.query_vars: tuple[object, ...] | None = None
        self.rows: list[tuple[Any, ...]] = [
            ("Weather context", {"station": "Pullman"}),
        ]
        FakePgVectorConnection.last_instance = self

    def simple_query(self, sql_query: bytes, query_vars: tuple[object, ...]):
        """Record query details and return fake rows."""
        self.query = sql_query
        self.query_vars = query_vars
        return iter(self.rows)


class FakeCursor:
    """Cursor double for insert tests."""

    def __init__(self, returned_ids: list[tuple[str] | None]) -> None:
        """Set the rows returned by successive inserts."""
        self.returned_ids = returned_ids
        self.executed: list[tuple[Any, ...]] = []

    def __enter__(self) -> FakeCursor:
        """Enter the cursor context."""
        return self

    def __exit__(self, exc_type, exc_value, exc_tb) -> None:
        """Exit the cursor context."""

    def execute(self, query: object, params: tuple[object, ...]) -> None:
        """Record the SQL and bound parameters."""
        self.executed.append((query, params))

    def fetchone(self) -> tuple[str] | None:
        """Return the next configured insert id."""
        return self.returned_ids.pop(0)


class FakeConnection:
    """Connection double used by document insertion tests."""

    def __init__(self, cursor: FakeCursor) -> None:
        """Set up the cursor and commit counter."""
        self._cursor = cursor
        self.commits = 0

    def cursor(self) -> FakeCursor:
        """Return the configured cursor."""
        return self._cursor

    def commit(self) -> None:
        """Record a transaction commit."""
        self.commits += 1


def test_similarity_search_queries_daily_index(monkeypatch) -> None:
    """Check similarity search embeds the query and maps pgvector rows to documents."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)

    store = PgVectorStore(FakeEmbedding())
    documents = store.similarity_search("What is the weather?", k=2)
    connection = FakePgVectorConnection.last_instance

    assert connection is not None
    assert connection.query is not None
    assert b"daily_index" in connection.query
    assert b"<->" in connection.query
    assert connection.query_vars == ("[0.1,0.2,0.3]", 2)
    assert documents == [Document(page_content="Weather context", metadata={"station": "Pullman"})]


def test_similarity_search_returns_empty_list_for_empty_table(monkeypatch) -> None:
    """Check empty pgvector results map to an empty document list."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)

    store = PgVectorStore(FakeEmbedding())
    connection = FakePgVectorConnection.last_instance
    assert connection is not None
    connection.rows = []

    assert store.similarity_search("What is the weather?") == []


def test_similarity_search_combines_metadata_and_staleness_filters(monkeypatch) -> None:
    """Combine JSON metadata constraints with the table's timestamp cutoff."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)

    store = PgVectorStore(FakeEmbedding(), table="live_index", staleness_days=7)
    documents = store.similarity_search("Weather?", k=4, filter={"county": "Whitman"})
    connection = FakePgVectorConnection.last_instance

    assert connection is not None
    assert connection.query is not None
    assert b"metadata @>" in connection.query
    assert b"CURRENT_DATE" in connection.query
    assert connection.query_vars == ('{"county": "Whitman"}', "timestamp", 7, "[0.1,0.2,0.3]", 4)
    assert documents == [Document(page_content="Weather context", metadata={"station": "Pullman"})]


def test_similarity_search_replaces_null_metadata_with_empty_dict(monkeypatch) -> None:
    """Return documents with an empty metadata mapping for null database values."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)

    store = PgVectorStore(FakeEmbedding())
    connection = FakePgVectorConnection.last_instance
    assert connection is not None
    connection.rows = [("Weather context", None)]

    assert store.similarity_search("Weather?") == [Document(page_content="Weather context", metadata={})]


def test_constructor_rejects_unsupported_table() -> None:
    """Reject a table outside the vector store's supported indexes."""
    with pytest.raises(ValueError, match="unsupported vector store table"):
        PgVectorStore(FakeEmbedding(), table="users")


def test_table_property_returns_configured_index(monkeypatch) -> None:
    """Expose the configured table name through the vector-store interface."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding(), table="forecast_index")

    assert store.table == "forecast_index"


def test_distinct_metadata_values_allowlisted_keys_and_filter_empty_rows(monkeypatch) -> None:
    """Return only non-empty distinct values from an allowlisted metadata key."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding())
    connection = FakePgVectorConnection.last_instance
    assert connection is not None
    connection.rows = [("Pullman",), (None,), ("",), ("Whitman",)]

    assert store.distinct_metadata_values("station") == ["Pullman", "Whitman"]
    assert connection.query == b"SELECT DISTINCT metadata->>'station' FROM daily_index"


def test_distinct_metadata_values_reject_unsupported_key(monkeypatch) -> None:
    """Reject metadata keys that are not in the SQL allowlist."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding())

    with pytest.raises(ValueError, match="unsupported metadata key"):
        store.distinct_metadata_values("anything' OR 1=1 --")


def test_add_documents_embeds_inserts_serializes_metadata_and_commits(monkeypatch) -> None:
    """Insert embedded documents and return generated ids after a commit."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding())
    cursor = FakeCursor([("doc-1",), ("doc-2",)])
    connection = FakeConnection(cursor)
    store._vector_db.conn = cast(Any, connection)
    documents = [
        Document(page_content="First", metadata={"date": date(2026, 9, 27)}),
        Document(page_content="Second", metadata={"station": "Pullman"}),
    ]

    assert store.add_documents(documents) == ["doc-1", "doc-2"]
    assert connection.commits == 1
    assert [json.loads(params[2]) for _, params in cursor.executed] == [
        {"date": "2026-09-27"},
        {"station": "Pullman"},
    ]
    assert [params[0] for _, params in cursor.executed] == ["[0.1,0.2,0.3]", "[0.1,0.2,0.3]"]


def test_add_documents_raises_when_database_returns_no_insert_id(monkeypatch) -> None:
    """Surface a failed insert rather than returning an incomplete id list."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding())
    connection = FakeConnection(FakeCursor([None]))
    store._vector_db.conn = cast(Any, connection)
    with pytest.raises(RuntimeError, match="Insert failed"):
        store.add_documents([Document(page_content="First")])
    assert connection.commits == 0


@pytest.mark.parametrize("table", ["daily_index", "live_index", "forecast_index"])
def test_station_date_selection_filters_records(monkeypatch, table: str) -> None:
    """Keep location and dates together with metadata filters and freshness limits."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding(), table=table, staleness_days=30)
    connection = FakePgVectorConnection.last_instance
    assert connection is not None
    connection.rows = [
        (
            "| timestamp | temperature in F |\n| --- | --- |\n"
            "| 2026-09-09 12:00:00 | 72 |\n| 2026-09-10 12:00:00 | 85 |",
            {"id": "1", "county": "Whitman", "date": "2026-09-09", "timestamp": "2026-09-09 12:00:00"},
        )
    ]
    selection = WeatherQuery(("1",), date(2026, 9, 9), date(2026, 9, 9), "Whitman")
    documents = store.similarity_search("temperature", k=1, filter={"state": "WA"}, selection=selection)
    assert connection.query is not None
    assert connection.query.index(b"WHERE") < connection.query.index(b"ORDER BY") < connection.query.index(b"LIMIT")
    assert b"metadata->>'id' = ANY(%s)" in connection.query
    assert b"lower(metadata->>'county') = %s" in connection.query
    assert b"metadata @> %s::jsonb" in connection.query
    field = "date" if table == "daily_index" else "timestamp"
    assert connection.query_vars == (
        ["1"],
        "2026-09-09",
        "2026-09-09",
        "whitman",
        '{"state": "WA"}',
        field,
        30,
        "[0.1,0.2,0.3]",
        1,
    )
    assert len(documents) == 1
    assert documents[0].metadata["id"] == "1"
    if table == "forecast_index":
        assert documents[0].metadata["dates"] == ["2026-09-09"]
        assert "timestamp" not in documents[0].metadata
        assert "2026-09-10" not in documents[0].page_content
        assert "72" in documents[0].page_content
    else:
        assert documents[0].metadata["timestamp"] == "2026-09-09 12:00:00"


@pytest.mark.parametrize(
    "metadata",
    [
        {"id": "2", "county": "Whitman", "date": "2026-09-09"},
        {"id": "1", "county": "Spokane", "date": "2026-09-09"},
        {"id": "1", "county": "Whitman", "date": "2026-09-10"},
        {"id": "1", "county": "Whitman", "date": "2026-09-99"},
        {"id": "1", "county": "Whitman"},
    ],
)
def test_discard_records_outside_selection(monkeypatch, metadata: dict) -> None:
    """Mismatched or malformed returned records must not reach the answer model."""
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", FakePgVectorConnection)
    store = PgVectorStore(FakeEmbedding())
    connection = FakePgVectorConnection.last_instance
    assert connection is not None
    connection.rows = [("wrong record", metadata)]
    selection = WeatherQuery(("1",), date(2026, 9, 9), date(2026, 9, 9), "Whitman")
    assert store.similarity_search("temperature", selection=selection) == []
