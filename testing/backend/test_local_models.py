"""Unit tests for the llama-cpp and Ollama model wrappers (no model files or servers required)."""

from unittest.mock import MagicMock, patch

import pytest
from backend.models._chatbot_base import _BaseChatbot
from backend.models._embedding_base import _BaseEmbedding
from backend.models.chatbot_local import ChatbotLlamaCpp, ChatbotOllama
from backend.models.embedding_local import EmbeddingLlamaCpp, EmbeddingOllama
from langchain_core.documents import Document

_DIMS = _BaseEmbedding._VECTOR_DIMENSIONS

# (wrapper class, patch target of the wrapped langchain class, kwargs as found in models.yaml, key holding the model)
_CHATBOTS = [
    (ChatbotLlamaCpp, "langchain_community.chat_models.ChatLlamaCpp", {"model_path": "m.gguf", "n_ctx": 4096}),
    (ChatbotOllama, "langchain_ollama.ChatOllama", {"model": "llama3.2", "temperature": 0}),
]
_EMBEDDINGS = [
    (EmbeddingLlamaCpp, "langchain_community.embeddings.LlamaCppEmbeddings", {"model_path": "e.gguf"}),
    (EmbeddingOllama, "langchain_ollama.OllamaEmbeddings", {"model": "nomic-embed-text"}),
]


@pytest.mark.parametrize(("wrapper", "target", "kwargs"), _CHATBOTS)
def test_chatbot_passes_kwargs_and_returns_text(wrapper, target, kwargs) -> None:
    """Chatbot wrappers forward yaml kwargs to langchain and return the response text."""
    with patch(target) as mock_cls:
        mock_cls.return_value.invoke.return_value = MagicMock(content="hello world!")
        chatbot = wrapper(dict(kwargs))
        mock_cls.assert_called_once_with(**kwargs)
        assert isinstance(chatbot, _BaseChatbot)
        assert chatbot.invoke(["say hello"]) == "hello world!"
        mock_cls.return_value.invoke.assert_called_once_with(["say hello"])


@pytest.mark.parametrize(("wrapper", "target", "kwargs"), _CHATBOTS)
def test_chatbot_flattens_list_content(wrapper, target, kwargs) -> None:
    """List style message content is joined into a single string."""
    with patch(target) as mock_cls:
        mock_cls.return_value.invoke.return_value = MagicMock(content=["a", {"type": "text", "text": "b"}])
        assert wrapper(dict(kwargs)).invoke(["hi"]) == "a\nb"


@pytest.mark.parametrize(("wrapper", "target", "kwargs"), _EMBEDDINGS)
def test_embedding_document_truncates_to_db_width(wrapper, target, kwargs) -> None:
    """Embedding wrappers return a db width vector paired with the source document."""
    with patch(target) as mock_cls:
        mock_cls.return_value.embed_query.return_value = [0.1] * (_DIMS + 256)
        model = wrapper({**kwargs, "temperature": 0} if "model_path" in kwargs else dict(kwargs))
        mock_cls.assert_called_once_with(**kwargs)
        assert isinstance(model, _BaseEmbedding)
        doc = Document(page_content="hello", metadata={})
        vector, returned_doc = model.embed_document(doc)
    assert len(vector) == _DIMS
    assert returned_doc is doc


@pytest.mark.parametrize(("wrapper", "target", "kwargs"), _EMBEDDINGS)
def test_embedding_documents_batches_and_keeps_order(wrapper, target, kwargs) -> None:
    """All documents are embedded in one call and paired with their source document."""
    docs = [Document(page_content=str(i), metadata={}) for i in range(3)]
    with patch(target) as mock_cls:
        mock_cls.return_value.embed_documents.return_value = [[float(i)] * _DIMS for i in range(3)]
        results = wrapper(dict(kwargs)).embed_documents(docs)
        mock_cls.return_value.embed_documents.assert_called_once_with(["0", "1", "2"])
    assert [d for _, d in results] == docs
    assert [v[0] for v, _ in results] == [0.0, 1.0, 2.0]


@pytest.mark.parametrize(("wrapper", "target", "kwargs"), _EMBEDDINGS)
def test_embedding_rejects_small_vectors(wrapper, target, kwargs) -> None:
    """Models producing fewer dimensions than the db column raise a clear error."""
    with patch(target) as mock_cls:
        mock_cls.return_value.embed_query.return_value = [0.1] * 384
        model = wrapper(dict(kwargs))
        with pytest.raises(ValueError, match="384 dimensions"):
            model.embed_document(Document(page_content="hello", metadata={}))
