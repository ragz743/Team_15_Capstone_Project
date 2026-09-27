"""The vector store wrapper class."""

import warnings

from backend.databases.pgvector import PgVectorConnection
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore


class PgVectorStore(VectorStore):
    """The local pgvector postgreSQL VectorStore class."""

    _embedding_model: _BaseEmbedding
    _vector_db: PgVectorConnection
    _table: str

    _ALLOWED_TABLES = frozenset({"daily_index", "live_index", "forecast_index"})

    def __init__(self, embedding_model: _BaseEmbedding, table: str = "daily_index") -> None:
        """Create an instance of the PgVectorStore class."""
        if table not in self._ALLOWED_TABLES:
            msg = f"unsupported vector store table: {table}"
            raise ValueError(msg)

        self._embedding_model = embedding_model
        self._vector_db = PgVectorConnection()
        self._table = table

    def add_documents(self, documents: list[Document], **kwargs) -> list[str]:
        """Add or update documents in the vector store."""
        raise NotImplementedError

    def aadd_documents(self, documents, **kwargs):
        """Async add or update documents in the vector store."""
        raise NotImplementedError

    def similarity_search(self, query: str, k: int = 4, **kwargs) -> list[Document]:
        """Return a list of documents found during semantic search."""
        query_embedding, _ = self._embedding_model.embed_document(Document(page_content=query))
        vector_value = "[" + ",".join(str(value) for value in query_embedding) + "]"
        sql_query = f"""
            SELECT document, metadata
            FROM {self._table}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """.encode()

        rows = self._vector_db.simple_query(sql_query, (vector_value, k))
        return [Document(page_content=str(row[0]), metadata=row[1] or {}) for row in rows]

    @warnings.deprecated("not supported for this project.")
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
