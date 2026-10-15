"""Unit tests for the EmbeddingLocal class (no running server required)."""

from unittest.mock import patch

import pytest
from backend.models.embedding_local import EmbeddingLocal
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

_DIMS = EmbeddingLocal._VECTOR_DIMENSIONS


def _make_model() -> EmbeddingLocal:
    return EmbeddingLocal({"model": "nomic-embed-text", "base_url": "http://localhost:8081/v1", "temperature": 0})


def test_embed_document_truncates_to_db_width() -> None:
    """Vectors wider than the db column are truncated."""
    model = _make_model()
    doc = Document(page_content="hello", metadata={"id": 1})
    with patch.object(OpenAIEmbeddings, "embed_query", return_value=[0.1] * (_DIMS + 256)):
        vector, returned_doc = model.embed_document(doc)
    assert len(vector) == _DIMS
    assert returned_doc is doc


def test_embed_documents_batches_and_keeps_order() -> None:
    """All documents are embedded in one call and paired with their source document."""
    model = _make_model()
    docs = [Document(page_content=str(i), metadata={}) for i in range(3)]
    vectors = [[float(i)] * _DIMS for i in range(3)]
    with patch.object(OpenAIEmbeddings, "embed_documents", return_value=vectors) as mock_embed:
        results = model.embed_documents(docs)
    mock_embed.assert_called_once_with(["0", "1", "2"])
    assert [d for _, d in results] == docs
    assert [v[0] for v, _ in results] == [0.0, 1.0, 2.0]


def test_embed_document_rejects_small_vectors() -> None:
    """Models producing fewer dimensions than the db column raise a clear error."""
    model = _make_model()
    doc = Document(page_content="hello", metadata={})
    with patch.object(OpenAIEmbeddings, "embed_query", return_value=[0.1] * 384):
        with pytest.raises(ValueError, match="384 dimensions"):
            model.embed_document(doc)
