"""The base class for an embedding model."""

from abc import ABC, abstractmethod

from langchain_core.documents import Document


class _BaseEmbedding(ABC):
    """The embedding model base class."""

    _VECTOR_DIMENSIONS = 768

    @abstractmethod
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        """Embed a document into a vector."""
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        """Embed multiple documents into vectors."""
        raise NotImplementedError
