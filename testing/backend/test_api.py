"""Tests for backend.api."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import backend.api as api
import pytest
from fastapi.testclient import TestClient


class FakeRetriever:
    """Small retriever test double that records the latest question."""

    def __init__(self) -> None:
        """Create a fake retriever."""
        self.question: str | None = None
        self.point = None

    def retrieve(self, question: str, *, point=None, history=None) -> str:
        """Return a deterministic response for API tests."""
        self.question = question
        self.point = point
        return f"retrieved: {question}"


def test_health_returns_readiness_metadata(monkeypatch) -> None:
    """Check health response includes API readiness state."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding-model")
    monkeypatch.setattr(api, "_chatbot", object())
    monkeypatch.setattr(api, "_retriever", object())
    monkeypatch.setattr(api, "_chatbot_model_name", "test-chat-model")
    monkeypatch.setattr(api, "_embedding_model_name", "test-embedding-model")

    client = TestClient(api.app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "chatbot_ready": True,
        "retriever_ready": True,
        "history_ready": False,
        "model": "test-chat-model",
        "embedding_model": "test-embedding-model",
        "has_api_key": True,
        "has_embedding_model": True,
    }


def test_chat_calls_retriever_with_latest_user_message(monkeypatch) -> None:
    """Check /api/chat sends the latest user turn into Retriever.retrieve."""
    retriever = FakeRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_chatbot_model_name", "test-chat-model")

    client = TestClient(api.app)
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "latest question"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "retrieved: latest question", "model": "test-chat-model"}
    assert retriever.question == "latest question"


def test_chat_rejects_empty_messages(monkeypatch) -> None:
    """Check empty message lists fail request validation."""
    monkeypatch.setattr(api, "_retriever", FakeRetriever())

    client = TestClient(api.app)
    response = client.post("/api/chat", json={"messages": []})

    assert response.status_code == 422


def test_chat_requires_user_message(monkeypatch) -> None:
    """Check conversations without a user turn fail with a clear client error."""
    monkeypatch.setattr(api, "_retriever", FakeRetriever())

    client = TestClient(api.app)
    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "assistant", "content": "hello"}]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "At least one user message is required."


@pytest.mark.parametrize(
    ("setting", "expected"),
    [(None, "openrouter/free"), ("", "openrouter/free"), ("  ", "openrouter/free"), ("custom/model", "custom/model")],
)
def test_startup_uses_default_or_explicit_chat_setting(monkeypatch, setting, expected):
    """Start successfully with unset settings and preserve explicit overrides."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding-model")
    monkeypatch.setenv("OPENROUTER_CHAT_TEMPERATURE", "0")
    monkeypatch.setenv("OPENROUTER_HISTORY_MODEL", "  ")
    if setting is None:
        monkeypatch.delenv("OPENROUTER_CHAT_MODEL", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_CHAT_MODEL", setting)
    monkeypatch.setattr(api.dotenv, "load_dotenv", lambda: None)
    chatbot = MagicMock()
    monkeypatch.setattr(api, "ChatbotOpenRouter", chatbot)
    monkeypatch.setattr(api, "EmbeddingOpenRouter", MagicMock())
    monkeypatch.setattr(api, "PgVectorStore", MagicMock())
    monkeypatch.setattr(api, "Retriever", MagicMock(return_value=FakeRetriever()))
    for name in ("_chatbot", "_retriever", "_chatbot_model_name", "_embedding_model_name", "_history_service"):
        monkeypatch.setattr(api, name, getattr(api, name))

    with TestClient(api.app) as client:
        health = client.get("/api/health").json()
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Temperature yesterday?"}]})

    assert chatbot.call_count == 2
    assert [call.args[0]["model"] for call in chatbot.call_args_list] == [expected, expected]
    assert health["chatbot_ready"] and health["retriever_ready"]
    assert health["model"] == expected
    assert response.status_code == 200
    assert response.json()["model"] == expected


def test_build_retriever_requires_embedding_model(monkeypatch) -> None:
    """Require an embedding model before constructing retrieval components."""
    monkeypatch.delenv("OPENROUTER_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_EMBEDDING_MODEL"):
        api._build_retriever()


def test_build_retriever_configures_models_and_all_indexes(monkeypatch) -> None:
    """Build retriever dependencies from environment settings."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test-chat")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setenv("OPENROUTER_CHAT_TEMPERATURE", "0.25")
    embedding = object()
    chatbot = object()
    stores: list[tuple[object, str, int | None]] = []
    monkeypatch.setattr(api, "EmbeddingOpenRouter", lambda name: embedding)
    monkeypatch.setattr(api, "ChatbotOpenRouter", lambda kwargs: chatbot)
    monkeypatch.setattr(
        api,
        "PgVectorStore",
        lambda model, table, staleness_days=None: stores.append((model, table, staleness_days)) or MagicMock(),
    )
    retriever = object()
    retriever_args: list[tuple[list[object], object]] = []

    def make_retriever(vector_stores, model):
        retriever_args.append((vector_stores, model))
        return retriever

    monkeypatch.setattr(api, "Retriever", make_retriever)

    result = api._build_retriever()

    assert result == (retriever, chatbot, "test-chat", "test-embedding")
    assert stores == [
        (embedding, "daily_index", None),
        (embedding, "live_index", 30),
        (embedding, "forecast_index", 2),
    ]
    assert len(retriever_args[0][0]) == 3
    assert retriever_args[0][1] is chatbot


def test_build_retriever_uses_default_chat_model_and_temperature(monkeypatch) -> None:
    """Use API defaults when optional chat settings are absent."""
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding")
    monkeypatch.delenv("OPENROUTER_CHAT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_CHAT_TEMPERATURE", raising=False)
    chatbot_args: list[dict] = []
    monkeypatch.setattr(api, "EmbeddingOpenRouter", lambda name: object())
    monkeypatch.setattr(api, "ChatbotOpenRouter", lambda kwargs: chatbot_args.append(kwargs) or object())
    monkeypatch.setattr(api, "PgVectorStore", lambda *args, **kwargs: object())
    monkeypatch.setattr(api, "Retriever", lambda *args: object())

    retriever, chatbot, model_name, embedding_name = api._build_retriever()

    assert retriever is not None
    assert chatbot is not None
    assert model_name == api._DEFAULT_CHAT_MODEL
    assert embedding_name == "test-embedding"
    assert chatbot_args == [{"model": api._DEFAULT_CHAT_MODEL, "temperature": 0.0}]


def test_lifespan_initializes_components_and_clears_them_after_failure(monkeypatch) -> None:
    """Initialize service globals on success and expose unavailable state on failure."""
    monkeypatch.setattr(api.dotenv, "load_dotenv", lambda: None)
    monkeypatch.setattr(api, "ChatbotOpenRouter", MagicMock())
    monkeypatch.setattr(api, "_history_service", None)
    retriever, chatbot = object(), object()
    monkeypatch.setattr(api, "_build_retriever", lambda: (retriever, chatbot, "chat", "embedding"))
    monkeypatch.setattr(api, "_retriever", None)
    monkeypatch.setattr(api, "_chatbot", None)
    monkeypatch.setattr(api, "_chatbot_model_name", "")
    monkeypatch.setattr(api, "_embedding_model_name", "")

    async def run_lifespan() -> None:
        async with api.lifespan(api.app):
            assert api._retriever is retriever
            assert api._chatbot is chatbot
            assert api._chatbot_model_name == "chat"
            assert api._embedding_model_name == "embedding"

    asyncio.run(run_lifespan())

    def fail_build():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(api, "_build_retriever", fail_build)

    async def run_failed_lifespan() -> None:
        async with api.lifespan(api.app):
            assert api._retriever is None
            assert api._chatbot is None
            assert api._chatbot_model_name == ""
            assert api._embedding_model_name == ""

    asyncio.run(run_failed_lifespan())


def test_retrieval_error_maps_rate_limits_and_general_failures() -> None:
    """Return a retryable status for rate limiting and gateway status otherwise."""
    from fastapi import HTTPException
    from openai import RateLimitError

    rate_limit = RateLimitError("limited", response=MagicMock(), body={})

    rate_error = api._retrieval_error(rate_limit)
    service_error = api._retrieval_error(RuntimeError("backend failure"))

    assert isinstance(rate_error, HTTPException)
    assert rate_error.status_code == 503
    assert service_error.status_code == 502


def test_chat_rejects_unavailable_service_and_empty_retrieval_response(monkeypatch) -> None:
    """Return service errors when startup did not initialize or retrieval is empty."""
    client = TestClient(api.app)
    payload = {"messages": [{"role": "user", "content": "weather?"}]}
    monkeypatch.setattr(api, "_retriever", None)
    assert client.post("/api/chat", json=payload).status_code == 503

    monkeypatch.setattr(api, "_retriever", MagicMock(retrieve=lambda *args, **kwargs: ""))
    assert client.post("/api/chat", json=payload).status_code == 502
