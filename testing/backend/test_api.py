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

    def retrieve(self, question: str, *, point=None, station_id=None, history=None) -> str:
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
        "engine": "langgraph",
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
    [
        (None, "nvidia/nemotron-3.5-super-vl:free"),
        ("", "nvidia/nemotron-3.5-super-vl:free"),
        ("  ", "nvidia/nemotron-3.5-super-vl:free"),
        ("custom/model", "custom/model"),
    ],
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
    for name in ("AWN_DB_HOST", "AWN_DB_USER", "AWN_DB_PASSWORD"):
        monkeypatch.setenv(name, "test")
    for name in ("OPENROUTER_WORKFLOW_MODEL", "OPENROUTER_CLASSIFIER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api, "LangGraphEngine", MagicMock(return_value=FakeRetriever()))
    for name in ("_chatbot", "_retriever", "_chatbot_model_name", "_embedding_model_name", "_history_service"):
        monkeypatch.setattr(api, name, getattr(api, name))

    with TestClient(api.app) as client:
        health = client.get("/api/health").json()
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Temperature yesterday?"}]})

    assert chatbot.call_count == 3
    assert [call.args[0]["model"] for call in chatbot.call_args_list] == [expected, expected, expected]
    assert health["chatbot_ready"] and health["retriever_ready"]
    assert health["model"] == expected
    assert response.status_code == 200
    assert response.json()["model"] == expected


@pytest.mark.parametrize("missing", ["OPENROUTER_API_KEY", "AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST"])
def test_build_retriever_requires_workflow_configuration(monkeypatch, missing) -> None:
    """Require model and AWN credentials before constructing the workflow."""
    for name in ("OPENROUTER_API_KEY", "AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.delenv(missing)
    chatbot = MagicMock()
    monkeypatch.setattr(api, "ChatbotOpenRouter", chatbot)

    with pytest.raises(ValueError, match="model and AWN database configuration"):
        api._build_retriever()
    chatbot.assert_not_called()


def test_build_retriever_configures_workflow_and_classifier_models(monkeypatch) -> None:
    """Build the graph with independently configured workflow and classifier models."""
    for name in ("OPENROUTER_API_KEY", "AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test-chat")
    monkeypatch.setenv("OPENROUTER_WORKFLOW_MODEL", "test-workflow")
    monkeypatch.setenv("OPENROUTER_CLASSIFIER_MODEL", "test-classifier")
    chatbot, classifier, engine = object(), object(), object()
    model_factory = MagicMock(side_effect=[chatbot, classifier])
    engine_factory = MagicMock(return_value=engine)
    monkeypatch.setattr(api, "ChatbotOpenRouter", model_factory)
    monkeypatch.setattr(api, "LangGraphEngine", engine_factory)

    result = api._build_retriever()

    assert result == (engine, chatbot, "test-workflow", "")
    assert [call.args[0]["model"] for call in model_factory.call_args_list] == ["test-workflow", "test-classifier"]
    assert all(call.args[0]["temperature"] == 0 for call in model_factory.call_args_list)
    engine_factory.assert_called_once_with(chatbot, classifier)


def test_build_retriever_uses_default_chat_model_and_temperature(monkeypatch) -> None:
    """Default both graph models to the API chat model with deterministic settings."""
    for name in ("OPENROUTER_API_KEY", "AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST"):
        monkeypatch.setenv(name, "test-value")
    for name in ("OPENROUTER_CHAT_MODEL", "OPENROUTER_WORKFLOW_MODEL", "OPENROUTER_CLASSIFIER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    chatbot_args: list[dict] = []
    monkeypatch.setattr(api, "ChatbotOpenRouter", lambda kwargs: chatbot_args.append(kwargs) or object())
    monkeypatch.setattr(api, "LangGraphEngine", lambda *args: object())

    retriever, chatbot, model_name, embedding_name = api._build_retriever()

    assert retriever is not None
    assert chatbot is not None
    assert model_name == api._DEFAULT_CHAT_MODEL
    assert embedding_name == ""
    assert len(chatbot_args) == 2
    assert all(kwargs["model"] == api._DEFAULT_CHAT_MODEL and kwargs["temperature"] == 0 for kwargs in chatbot_args)


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
