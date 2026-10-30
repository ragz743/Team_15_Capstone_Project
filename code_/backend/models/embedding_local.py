"""Embedding wrappers for locally hosted models (llama.cpp server, in-process llama-cpp, Ollama)."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from backend.models._embedding_base import _BaseEmbedding
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

if TYPE_CHECKING:
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings


class _LangchainEmbedding(_BaseEmbedding):
    """Shared embed logic for embedding models backed by a langchain Embeddings class."""

    _model: Embeddings

    @override
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        return self._fit_dimensions(self._model.embed_query(document.page_content)), document

    @override
    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        vectors = self._model.embed_documents([d.page_content for d in documents])
        return [(self._fit_dimensions(v), d) for v, d in zip(vectors, documents, strict=True)]


class EmbeddingLocal(_LangchainEmbedding):
    """Factory compatible wrapper for a llama.cpp embedding server (OpenAI-compatible API)."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of EmbeddingLocal."""
        config = dict(kwargs)
        model: str = config.pop("model")
        base_url: str = config.pop("base_url")
        config.pop("temperature", None)  # not applicable to embeddings

        model_kwargs = config.pop("model_kwargs", {})
        model_kwargs["encoding_format"] = "float"

        self._model = OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=SecretStr("local"),  # local servers do not validate the key
            check_embedding_ctx_length=False,  # skip tiktoken, local models use their own tokenizer
            model_kwargs=model_kwargs,
            **config,
        )


class EmbeddingLlamaCpp(_LangchainEmbedding):
    """Factory compatible wrapper for running a GGUF model in-process with langchain-community LlamaCppEmbeddings."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of EmbeddingLlamaCpp."""
        # imported here so the optional [local] dependencies are only needed when this class is used
        from langchain_community.embeddings import LlamaCppEmbeddings

        config = dict(kwargs)
        model_path: str = config.pop("model_path")
        config.pop("temperature", None)  # not applicable to embeddings
        self._model = LlamaCppEmbeddings(model_path=model_path, **config)


class EmbeddingOllama(_LangchainEmbedding):
    """Factory compatible wrapper for a model served by Ollama with langchain-ollama OllamaEmbeddings."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of EmbeddingOllama."""
        from langchain_ollama import OllamaEmbeddings

        config = dict(kwargs)
        model: str = config.pop("model")
        self._model = OllamaEmbeddings(model=model, **config)  # base_url defaults to http://localhost:11434
