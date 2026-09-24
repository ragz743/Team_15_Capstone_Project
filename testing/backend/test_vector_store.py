"""Tests for backend.vector_store."""

from __future__ import annotations

from datetime import date

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
        self.rows = [
            ("Weather context", {"station": "Pullman"}),
        ]
        FakePgVectorConnection.last_instance = self

    def simple_query(self, sql_query: bytes, query_vars: tuple[object, ...]):
        """Record query details and return fake rows."""
        self.query = sql_query
        self.query_vars = query_vars
        return iter(self.rows)


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
