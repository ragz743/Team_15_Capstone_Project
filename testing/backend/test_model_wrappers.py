"""Tests for supported OpenRouter and Copilot model wrappers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from backend.models import (
    chatbot_github_copilot,
    chatbot_openrouter,
    embedding_openrouter,
)
from backend.models.chatbot_local import ChatbotLlamaCpp, ChatbotLocal, ChatbotOllama
from copilot.session_events import AssistantMessageData
from langchain_core.documents import Document


@pytest.mark.parametrize("wrapper", [ChatbotLocal, ChatbotLlamaCpp, ChatbotOllama])
def test_local_chatbot_wrappers_are_concrete(wrapper) -> None:
    """All local LangChain wrappers implement the shared async chatbot interface."""
    assert not wrapper.__abstractmethods__


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("response text", "response text"),
        (["one"], "one"),
        ([{"first": 1, "second": "two"}], "1\ntwo"),
        ({"unmatched": "shape"}, ""),
    ],
)
def test_openrouter_chatbot_formats_supported_response_content(monkeypatch, content: Any, expected: str) -> None:
    """Convert string and single-item list model responses into text."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class FakeChatModel:
        async def ainvoke(self, messages: list[str]) -> SimpleNamespace:
            calls.append((messages, {}))
            return SimpleNamespace(content=content)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(chatbot_openrouter, "ChatOpenRouter", lambda **kwargs: FakeChatModel())
    config = {"model": "test-model", "temperature": 0.1}
    chatbot = chatbot_openrouter.ChatbotOpenRouter(config)

    assert asyncio.run(chatbot.ainvoke(["question"])) == expected
    assert calls == [(["question"], {})]
    assert config == {"temperature": 0.1}


def test_openrouter_embedding_configures_encoding_and_truncates_vectors(monkeypatch) -> None:
    """Set float encoding, cap vector size, preserve the document, and embed batches."""
    constructor_calls: list[dict[str, Any]] = []
    vectors: list[list[float]] = []

    class FakeEmbeddings:
        def embed_query(self, text: str) -> list[float]:
            vectors.append([float(len(text))] * 800)
            return vectors[-1]

    def construct_embeddings(**kwargs: Any) -> FakeEmbeddings:
        constructor_calls.append(kwargs)
        return FakeEmbeddings()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(embedding_openrouter, "OpenAIEmbeddings", construct_embeddings)
    embedding = embedding_openrouter.EmbeddingOpenRouter(
        {"model": "test-embedding", "temperature": 0.8, "model_kwargs": {"custom": True}}
    )
    first = Document(page_content="first", metadata={"station": "Pullman"})
    second = Document(page_content="second")

    vector, document = embedding.embed_document(first)
    batch = embedding.embed_documents([first, second])

    assert len(vector) == 768
    assert document is first
    assert [len(item[0]) for item in batch] == [768, 768]
    assert [item[1] for item in batch] == [first, second]
    assert constructor_calls == [
        {
            "model": "test-embedding",
            "api_key": "test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "check_embedding_ctx_length": False,
            "model_kwargs": {"custom": True, "encoding_format": "float"},
        }
    ]


class FakeSession:
    """Copilot session double with configurable response data."""

    def __init__(self, response: Any) -> None:
        """Store the response returned by the session."""
        self.response = response
        self.sent: list[str] = []

    async def __aenter__(self) -> FakeSession:
        """Enter the fake Copilot session."""
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb) -> None:
        """Exit the fake Copilot session."""

    async def send_and_wait(self, message: str) -> Any:
        """Record a prompt and return the configured response."""
        self.sent.append(message)
        return self.response


class FakeCopilotClient:
    """Copilot client double that supplies one fake session."""

    def __init__(self, session: FakeSession) -> None:
        """Store the session that should be created."""
        self.session = session
        self.session_kwargs: dict[str, Any] | None = None

    async def __aenter__(self) -> FakeCopilotClient:
        """Enter the fake Copilot client."""
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb) -> None:
        """Exit the fake Copilot client."""

    async def create_session(self, **kwargs: Any) -> FakeSession:
        """Capture session configuration and return the fake session."""
        self.session_kwargs = kwargs
        return self.session


def test_copilot_chatbot_joins_prompts_and_returns_assistant_message(monkeypatch) -> None:
    """Create a configured Copilot session and return its assistant content."""
    session = FakeSession(SimpleNamespace(data=AssistantMessageData(content="answer", message_id="message-1")))
    client = FakeCopilotClient(session)
    client_creations: list[FakeCopilotClient] = []

    def create_client() -> FakeCopilotClient:
        client_creations.append(client)
        return client

    monkeypatch.setattr(chatbot_github_copilot, "CopilotClient", create_client)
    kwargs = {"model": "test-model"}
    chatbot = chatbot_github_copilot.ChatbotCopilot(kwargs)

    assert asyncio.run(chatbot.ainvoke(["first", "second"])) == "answer"
    assert kwargs == {}
    assert session.sent == ["first\nsecond"]
    assert client_creations == [client]
    assert client.session_kwargs is not None
    assert client.session_kwargs["model"] == "test-model"
    assert client.session_kwargs["on_permission_request"] is not None


@pytest.mark.parametrize(
    ("response", "error_type", "error_text"),
    [
        (None, ValueError, "returned nothing"),
        (SimpleNamespace(data=SimpleNamespace()), TypeError, "unexpected event type"),
    ],
)
def test_copilot_chatbot_reports_missing_or_unexpected_events(
    monkeypatch,
    response: Any,
    error_type: type[Exception],
    error_text: str,
) -> None:
    """Raise explicit errors when Copilot returns no response or a non-assistant event."""
    session = FakeSession(response)
    monkeypatch.setattr(chatbot_github_copilot, "CopilotClient", lambda: FakeCopilotClient(session))
    chatbot = chatbot_github_copilot.ChatbotCopilot({"model": "test-model"})

    with pytest.raises(error_type, match=error_text):
        asyncio.run(chatbot.ainvoke(["question"]))
