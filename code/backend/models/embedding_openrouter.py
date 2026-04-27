"""A Wrapper for the langchain class to be instantiated by the model factory."""

import os
from typing import TYPE_CHECKING, override

from backend.models._embedding_base import _BaseEmbedding
from langchain_openai import OpenAIEmbeddings

if TYPE_CHECKING:
    from langchain_core.documents import Document


class EmbeddingOpenRouter(_BaseEmbedding):
    """Factory compatible ChatOpenRouter wrapper."""

    _BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model_name: str, **kwargs) -> None:
        """Create an instance of the ChatbotOpenRouter."""
        self._model = OpenAIEmbeddings(
            api_key=os.getenv("OPENROUTER_API_KEY"),  # type: ignore (can't get SecretStr type)
            base_url=self._BASE_URL,
            check_embedding_ctx_length=False,
            **kwargs,
        )

    @override
    def embed_document(self, document: Document) -> list[float]:
        # note: we only pass str content when embedding, but we store
        # metadata with the vector in the db
        return self._model.embed_query(document.page_content)

    @override
    def embed_documents(self, documents: list[Document]) -> list[list[float]]:
        return [self.embed_document(d) for d in documents]
