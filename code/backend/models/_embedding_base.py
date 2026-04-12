"""The base class for an embedding model."""

from abc import ABC, abstractmethod

from langchain_core.documents import Document


class _BaseEmbedding(ABC):
    """The embedding model base class."""

    @abstractmethod
    def embed_document(self, document: Document) -> list[float]:
        """Embed a document into a vector."""
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, documents: list[Document]) -> list[list[float]]:
        """Embed multiple documents into vectors."""
        raise NotImplementedError
