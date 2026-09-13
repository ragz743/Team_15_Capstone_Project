"""Exercise the HTTP chat contract using controlled weather records and model responses."""

from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.retriever import Retriever
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pytest import MonkeyPatch


def test_chat_passes_retrieved_weather_to_model_and_returns_reply(monkeypatch: MonkeyPatch) -> None:
    """Exercise API and real retriever together without external services."""
    store = MagicMock()
    store.similarity_search.return_value = [Document(page_content="Pullman, 2026-09-09: temperature 72°F.")]
    chatbot = MagicMock()
    chatbot.invoke.return_value = "Pullman's temperature on September 9 was 72°F."
    monkeypatch.setattr(api, "_retriever", Retriever(store, chatbot))
    monkeypatch.setattr(api, "_chatbot_model_name", "test-model")

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "  Temperature in Pullman?  "}]}
    )

    assert response.status_code == 200
    assert response.json() == {"reply": chatbot.invoke.return_value, "model": "test-model"}
    store.similarity_search.assert_called_once_with("Temperature in Pullman?")
    prompt = chatbot.invoke.call_args.args[0][0]
    assert "Pullman, 2026-09-09: temperature 72°F." in prompt
    assert "Temperature in Pullman?" in prompt


@pytest.mark.parametrize("content", ["", " ", "\n\t"])
def test_chat_rejects_blank_input_without_retrieval(monkeypatch: MonkeyPatch, content: str) -> None:
    """Reject empty and whitespace-only questions before any service calls."""
    retriever = MagicMock()
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post("/api/chat", json={"messages": [{"role": "user", "content": content}]})
    assert response.status_code in (400, 422)
    retriever.retrieve.assert_not_called()
