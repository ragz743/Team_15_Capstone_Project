"""Tests for backend.api."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("setting", "expected"),
    [(None, "openrouter/free"), ("", "openrouter/free"), ("  ", "openrouter/free"), ("custom/model", "custom/model")],
)
def test_startup_uses_default_or_explicit_chat_setting(monkeypatch, setting, expected):
    """Start successfully with unset settings and preserve explicit overrides."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding-model")
    monkeypatch.setenv("OPENROUTER_CHAT_TEMPERATURE", "0")
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
    for name in ("_chatbot", "_retriever", "_chatbot_model_name", "_embedding_model_name"):
        monkeypatch.setattr(api, name, getattr(api, name))

    with TestClient(api.app) as client:
        health = client.get("/api/health").json()
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Temperature yesterday?"}]})

    chatbot.assert_called_once_with({"model": expected, "temperature": 0.0})
    assert health["chatbot_ready"] and health["retriever_ready"]
    assert health["model"] == expected
    assert response.status_code == 200
    assert response.json()["model"] == expected


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
