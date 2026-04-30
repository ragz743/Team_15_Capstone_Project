"""A Wrapper for the langchain class to be instantiated by the model factory."""

import os
from typing import override

from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings


class EmbeddingOpenRouter(_BaseEmbedding):
    """Factory compatible ChatOpenRouter wrapper."""

    _BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of the EmbeddingOpenRouter."""
        model_name: str = kwargs.pop("model")
        # base_url: str = kwargs.pop("base_url", self._BASE_URL)
        self._model = OpenAIEmbeddings(
            model=model_name,
            api_key=os.getenv("OPENROUTER_API_KEY"),  # type: ignore (can't get SecretStr type)
            base_url=self._BASE_URL,
            check_embedding_ctx_length=False,
            **kwargs,
        )

    @override
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        return self._model.embed_query(document.page_content)[: self._VECTOR_DIMENSIONS], document

    @override
    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        return [self.embed_document(d) for d in documents]
