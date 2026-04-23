"""Embedding model backed by HTTP server (embedding-model container).

The docker-compose.yml starts a server for the embedding model (i.e. llama) on
port 8081. That server exposes an OpenAI-compatible /v1/embeddings endpoint.
This class wraps that endpoint and satisfies the _BaseEmbedding contract so
it can be wired through models.yaml exactly like any other embedding model (FR-18).

models.yaml entry
-----------------
models:
  embedding:
    class_file: "embedding.py"
    class: "Embedding"
    kwargs:
      base_url: "http://embedding:8081" # service name inside Docker network
      # base_url: "http://localhost:8081" # use this when running outside Docker
"""

from __future__ import annotations

import logging
import os

import requests
from langchain_core.documents import Document

from ._embedding_base import _BaseEmbedding

logger = logging.getLogger(__name__)

# Default timeout for a single embedding request (seconds).
# Kept tight because embeddings should be fast (NFR-1).
DEFAULT_TIMEOUT_S = 10


class Embedding(_BaseEmbedding):
    """Calls the llama.cpp /v1/embeddings endpoint to produce dense vectors."""

    def __init__(
        self,
        base_url: str = "http://embedding:8081",
        timeout: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Initialize the embedding client backed by the embedding-model Docker service.

        The server is started by the embedding-model Docker service defined in
        docker-compose-yml (port 8081). The model loaded there is controlled by
        the EMBEDDING_MODEL environment variable.

        Parameters
        ----------
        base_url:
          Base URL of the llama-server (no trailing slash).
          Defaults to http://embedding:8081 (Docker service name).
          Override with the EMBEDDING_BASE_URL env var for local development.
        timeout:
          Per-request HTTP timeout in seconds.

        """
        # Environment variable takes precedence over the kwarg (FR-18)
        self.base_url = os.environ.get("EMBEDDING_BASE_URL", base_url).rstrip("/")
        self.timeout = timeout
        self.endpoint = f"{self.base_url}/v1/embeddings"
        logger.info("Embedding: endpoint=%s", self.endpoint)

    # _BaseEmbedding interface

    def embed_document(self, document: Document) -> list[float]:
        """Embed a single LangChain Document and return its float vector."""
        return self.embed_text(document.page_content)

    def embed_documents(self, documents: list[Document]) -> list[list[float]]:
        """Embed a list of LangChain Documents in a single batched request.

        The llama-server accepts  list of strings in the 'input' field, so
        one HTTP round-trip handles the whole batch (NFR-1 latency).
        """
        texts = [d.page_content for d in documents]
        return self.embed_batch(texts)

    # Convenience helpers used directly by the RAG pipeline and loader

    def embed(self, text: str) -> list[float]:
        """Embed a plain string - shortcut used by RAGPipeline._stage3_retrieve().

        The pipeline calls self.embed.embed(user_query) (see rag_pipeline.py),
        so this method must exist alongside the base-class interface.
        """
        return self.embed_text(text)

    # Internal helpers

    def embed_text(self, text: str) -> list[float]:
        """Send a single-string embedding request."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """POST to /v1/embeddings and return a list of float vectors.

        Raises
        ------
        RuntimeError
          If the HTTP request fails or the response is malformed.

        """
        payload = {"input": texts}
        try:
            resp = requests.post(self.endpoint, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Embedding: request to {self.endpoint} failed: {exc}") from exc

        try:
            data = resp.json()
            # /v1/embeddings returns {"data": [{"embedding": [...], "index": 0}, ...]}
            items = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in items]
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Embedding: unexpected response format: {exc}\nRaw response: {resp.text[:500]}"
            ) from exc
