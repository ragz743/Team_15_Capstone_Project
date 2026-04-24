"""The vector store wrapper class."""

import json
import warnings

from backend.databases.pgvector import PgVectorConnection
from backend.loaders._loader_base import _BaseLoader
from backend.model_factory import ModelFactory
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore


class PgVectorStore(VectorStore):
    """The local pgvector postgreSQL VectorStore class."""

    _embedding_model: _BaseEmbedding
    _vector_db: PgVectorConnection

    def __init__(self, embedding_model: _BaseEmbedding) -> None:
        """Create an instance of the PgVectorStore class."""
        # NOTE: Need to implement, just load embedding. Doing both will have to do for now...
        self._embedding_model, _ = ModelFactory.load_from_models_yaml()

    def load_and_store(self, loader: _BaseLoader) -> list[str]:
        """Given a document loader, use it to load then embed vectors before storing."""
        docs: list[Document] = [d for d in loader.load() if d.page_content]
        embeddings = self._embedding_model.embed_documents(docs)

        with PgVectorConnection() as pgvec_conn:
            ids = [
                pgvec_conn.insert(loader.insert_sql, (vec, doc.page_content, json.dumps(doc.metadata)))
                for vec, doc in embeddings
            ]

        return ids

    def add_documents(self, documents: list[Document], **kwargs) -> list[str]:
        """Add or update documents in the vector store."""
        raise NotImplementedError

    def aadd_documents(self, documents, **kwargs):
        """Async add or update documents in the vector store."""
        raise NotImplementedError

    def similarity_search(self, query, k=4, **kwargs):
        """Return a list of documents found during semantic search."""
        raise NotImplementedError

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
