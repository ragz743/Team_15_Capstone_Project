"""A Wrapper for the langchain class to be instantiated by the model factory."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, override

from backend.models._embedding_base import _BaseEmbedding
from langchain_openai import OpenAIEmbeddings

if TYPE_CHECKING:
    from langchain_core.documents import Document


class EmbeddingOpenRouter(_BaseEmbedding):
    """Factory compatible ChatOpenRouter wrapper."""

    _BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model_name: str | dict, **kwargs) -> None:
        """Create an instance of the ChatbotOpenRouter."""
        if isinstance(model_name, dict):
            config = dict(model_name)
            model_name = str(config.pop("model"))
            config.pop("temperature", None)
            kwargs = {**config, **kwargs}

        self._model = OpenAIEmbeddings(
            model=model_name,
            api_key=os.getenv("OPENROUTER_API_KEY"),  # type: ignore (can't get SecretStr type)
            base_url=self._BASE_URL,
            check_embedding_ctx_length=False,
            # dimensions=self._VECTOR_DIMENSIONS,
            **kwargs,
        )

    @override
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        # note: we only pass str content when embedding, but we store
        # metadata with the vector in the db
        return self._model.embed_query(document.page_content)[: self._VECTOR_DIMENSIONS], document

    @override
    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        return [self.embed_document(d) for d in documents]
