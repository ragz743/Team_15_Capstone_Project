"""The vector store wrapper class."""

import json

from backend.databases.pgvector import PgVectorConnection
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from psycopg import sql


class PgVectorStore(VectorStore):
    """The local pgvector postgreSQL VectorStore class."""

    _embedding_model: _BaseEmbedding
    _vector_db: PgVectorConnection
    _table: str

    # Stores the embedding model, opens a PgVectorConnection, and accepts a table parameter (default "daily_index")
    # to match the schema in pgvector-seed.sql.
    def __init__(self, embedding_model: _BaseEmbedding, table: str = "daily_index") -> None:
        """Create an instance of the PgVectorStore class."""
        self._embedding_model = embedding_model
        self._vector_db = PgVectorConnection()
        self._table = table

    # Batches embedding via embed_documents, then inserts each (embedding, document, metadata) row using
    # pgvector's ::vector cast.
    # Metadata is json.dumps(..., default=str) to safely serialize date values from DailyLoader.
    # Returns auto-generated row IDs.
    def add_documents(self, documents: list[Document], **kwargs) -> list[str]:
        """Add or update documents in the vector store."""
        embeddings = self._embedding_model.embed_documents(documents)
        ids: list[str] = []
        with self._vector_db.conn.cursor() as cursor:
            for doc, (vec, _) in zip(documents, embeddings, strict=True):
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                query = sql.SQL(
                    "INSERT INTO {} (embedding, document, metadata) VALUES (%s::vector, %s, %s) RETURNING id"
                ).format(sql.Identifier(self._table))
                cursor.execute(
                    query,
                    (vec_str, doc.page_content, json.dumps(doc.metadata, default=str)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Insert failed: no row returned")
                ids.append(str(row[0]))
        self._vector_db.conn.commit()
        return ids

    def aadd_documents(self, documents, **kwargs):
        """Async add or update documents in the vector store."""
        raise NotImplementedError

    # Embeds the query string, then runs pgvector's <-> L2 nearest-neighbour operation and returns top-k results
    # as Document objects.
    def similarity_search(self, query: str, k: int = 4, **kwargs) -> list[Document]:
        # TODO: Implement metadata filtering later.
        # raise NotImplementedError
        """Return a list of documents found during semantic search."""
        query_vec, _ = self._embedding_model.embed_document(Document(page_content=query))
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
        rows = self._vector_db.simple_query(
            f"SELECT document, metadata FROM {self._table} ORDER BY embedding <-> %s::vector LIMIT %s".encode(),
            (vec_str, k),
        )
        return [Document(page_content=row[0], metadata=row[1] or {}) for row in rows]

    def from_texts(
        self,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict] | None = None,
        *args,
        ids: list[str] | None = None,
        **kwargs,
    ) -> VectorStore:
        """Interface requires this for compatibility, we do not need though! Do not implement."""
        raise NotImplementedError
