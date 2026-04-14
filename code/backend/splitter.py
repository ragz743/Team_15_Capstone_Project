"""Code for splitting documents into smaller chunks for RAG."""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Splitter:
    """Splits documents into smaller chunks for embedding & retrieval."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        """Create an instance of the Splitter class."""
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, documents: list[Document]) -> list[Document]:
        """Split a list of documents into smaller chunks."""
        return self._splitter.split_documents(documents)
