"""Tests for backend.vector_store."""

from __future__ import annotations

from backend.models._embedding_base import _BaseEmbedding
from backend.vector_store import PgVectorStore
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
    assert b"<=>" in connection.query
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
