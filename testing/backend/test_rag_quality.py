"""Sample test suite."""

from __future__ import annotations

from collections.abc import Callable

import backend.api as api
import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient


class ScriptedRetriever:
    """Retriever test double that returns a pre-set answer for each question."""

    def __init__(self, response: str) -> None:
        """Initialize the scripted retriever with a pre-set response."""
        self.response = response
        self.last_question: str | None = None

    def retrieve(self, question: str, filter: dict | None = None) -> str:
        """Return the pre-set response and record the incoming question."""
        self.last_question = question
        return self.response


def _chat(client: TestClient, question: str) -> str:
    """Post a single user message and return the reply string."""
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": question}]})
    assert response.status_code == 200, response.text
    return response.json()["reply"]


@pytest.fixture()
def client(
    monkeypatch: MonkeyPatch,
) -> Callable[[str], tuple[TestClient, ScriptedRetriever]]:
    """TestClient factory with a scripted retriever injected."""

    def _make_client(retriever_response: str) -> tuple[TestClient, ScriptedRetriever]:
        retriever = ScriptedRetriever(retriever_response)
        monkeypatch.setattr(api, "_retriever", retriever)
        monkeypatch.setattr(api, "_chatbot_model_name", "test-model")
        return TestClient(api.app), retriever

    return _make_client


def test_current_weather_question_reaches_retriever(client) -> None:
    """Chatbot forwards a current-weather question to the retriever unchanged."""
    c, retriever = client("Current temp in Pullman is 72°F.")
    _chat(c, "What is the current temperature in Pullman?")

    assert retriever.last_question == "What is the current temperature in Pullman?"


def test_historical_weather_question_reaches_retriever(client) -> None:
    """Chatbot forwards a historical question to the retriever unchanged."""
    c, retriever = client("Average temp in Pullman last week was 65°F.")
    _chat(c, "What was the average temperature in Pullman last week?")

    assert retriever.last_question == "What was the average temperature in Pullman last week?"


def test_forecast_question_reaches_retriever(client) -> None:
    """Chatbot forwards a forecast question to the retriever unchanged."""
    c, retriever = client("Forecast for Pullman: highs in the mid-70s.")
    _chat(c, "What is the forecast for Pullman this week?")

    assert retriever.last_question == "What is the forecast for Pullman this week?"


OUT_OF_SCOPE_QUESTIONS = [
    "Who won the 2026 World Cup?",
    "What is the capital of France?",
    "Write me a poem about Pullman.",
    "What is 2 + 2?",
    "Who are BTS?",
]

REFUSAL_PHRASES = [
    "don't have data",
    "cannot answer",
    "only answer",
    "not able to",
    "outside",
    "no information",
    "i don't have",
]


@pytest.mark.parametrize("question", OUT_OF_SCOPE_QUESTIONS)
def test_out_of_scope_question_is_refused(client, question: str) -> None:
    """Chatbot should refuse questions that have nothing to do with AWN data."""
    c, _ = client("I don't have data to answer that question.")
    reply = _chat(c, question).lower()

    message = f"Expected a refusal for out-of-scope question: '{question}'\nGot: '{reply}'"
    assert any(phrase in reply for phrase in REFUSAL_PHRASES), message


def test_multi_turn_uses_latest_question(client) -> None:
    """In a multi-turn conversation the retriever receives only the latest question."""
    c, retriever = client("Temp in Pullman today is 68°F.")
    c.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "What is the weather in Pullman?"},
                {"role": "assistant", "content": "It is 68°F."},
                {"role": "user", "content": "What about the humidity?"},
            ]
        },
    )

    assert retriever.last_question == "What about the humidity?"


def test_chat_503_when_retriever_not_initialized(monkeypatch: MonkeyPatch) -> None:
    """If the retriever failed to initialize, /api/chat returns 503."""
    monkeypatch.setattr(api, "_retriever", None)

    c = TestClient(api.app)
    response = c.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Any question"}]},
    )

    assert response.status_code == 503
