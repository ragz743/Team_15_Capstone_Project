"""Tests for backend.splitter."""

from backend.splitter import Splitter
from langchain_core.documents import Document


def test_splitter_returns_documents():
    """Check that split returns a list of documents."""
    splitter = Splitter()
    docs = [Document(page_content="On 2024-01-15, Pullman had avg temp of 45F.")]
    result = splitter.split(docs)
    assert isinstance(result, list)
    assert len(result) > 0


def test_splitter_preserves_metadata():
    """Check that split preserves document metadata."""
    splitter = Splitter()
    docs = [
        Document(
            page_content="On 2024-01-15, Pullman had avg temp of 45F.",
            metadata={"county": "Whitman"},
        )
    ]
    result = splitter.split(docs)
    assert result[0].metadata["county"] == "Whitman"


def test_splitter_chunks_large_document():
    """Check that a large document gets split into multiple chunks."""
    splitter = Splitter(chunk_size=50, chunk_overlap=10)
    long_text = "weather data " * 50
    docs = [Document(page_content=long_text)]
    result = splitter.split(docs)
    assert len(result) > 1
