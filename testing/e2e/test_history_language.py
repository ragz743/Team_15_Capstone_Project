"""Opt-in free-model evaluation of #67 using synthetic conversations only."""

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from backend.history_service import HistoryService
from backend.models.chatbot_openrouter import ChatbotOpenRouter

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HISTORY_MODEL_TESTS") != "1", reason="Opt-in external history-model evaluation"
)
NOW = datetime(2026, 9, 22, 17, tzinfo=UTC)


@pytest.fixture(scope="module")
def service():
    """Use only an explicitly named free model, without existing user history or weather calls."""
    import dotenv

    dotenv.load_dotenv()
    model_name = os.getenv("OPENROUTER_HISTORY_MODEL") or os.environ["OPENROUTER_CHAT_MODEL"]
    assert model_name.endswith(":free"), "This evaluation only authorizes a free chat model"
    model = ChatbotOpenRouter(
        {
            "model": model_name,
            "temperature": 0,
            "max_tokens": 1800,
            "request_timeout": 25000,
            "max_retries": 0,
        }
    )
    return HistoryService(model, model_name)


@pytest.mark.parametrize(
    ("question", "recent", "expected", "scope"),
    [
        ("what did i ask you about frost before?", [], "recall", "all"),
        ("can u bring back that frezing chat we had", [], "recall", "all"),
        ("Remind me what you told me about the cold snap", [], "recall", "all"),
        ("Give me a quick recap of our previous conversation", [], "recall", "previous"),
        ("What have we covered in this chat so far?", [], "recall", "current"),
        ("Using the location from our last conversation, check humidity today", [], "reuse", "previous"),
        ("whats the wather", [], "weather", "all"),  # codespell:ignore whats
        ("What was the weather at Pullman on September 10?", [], "weather", "all"),
        (
            "what about humidity?",
            [{"user": "Temperature at Pullman yesterday?", "assistant": "72 F"}],
            "weather",
            "all",
        ),
        ("the frost one", [{"user": "Can you find an old chat?", "assistant": "Which topic?"}], "recall", "all"),
    ],
)
def test_real_history_routing(service, question, recent, expected, scope):
    """Evaluate language recognition separately from the deterministic fixture suite."""
    store = MagicMock()
    store.history_window.return_value = recent
    store.search_history.return_value = []
    result = service.prepare(store, uuid4(), uuid4(), question, accepted_at=NOW)
    assert result.intent.action == expected, result.intent.model_dump()
    if expected != "weather":
        assert result.intent.scope == scope, result.intent.model_dump()


def test_real_conversation_date_and_grounded_summary(service):
    """Interpret a sent date, then summarize a saved claim without treating it as current weather."""
    store = MagicMock()
    store.history_window.return_value = []
    store.search_history.return_value = [
        {
            "title": "Frost discussion",
            "requested_at": datetime(2026, 9, 10, 17, tzinfo=UTC),
            "user_content": "Did frost affect Pullman on January 1?",
            "assistant_content": "No matching January records were available. I could not confirm frost.",
            "context": None,
        }
    ]
    result = service.prepare(
        store, uuid4(), uuid4(), "What did I ask about frost on September 10, 2026?", accepted_at=NOW
    )
    assert result.intent.action == "recall"
    assert str(result.intent.start) == str(result.intent.end) == "2026-09-10"
    reply = service.answer("Remind me what you said about frost then", result.snapshot)
    assert "[1]" in reply and "2026-09-10 10:00 PDT" in reply
    assert "not updated weather" in reply and "could not confirm frost" in reply


def test_real_relative_conversation_date_uses_reference_time(service):
    """Last Friday is computed against the accepted request date, not the current model date."""
    store = MagicMock()
    store.history_window.return_value = []
    store.search_history.return_value = []
    result = service.prepare(store, uuid4(), uuid4(), "What did we talk about last Friday?", accepted_at=NOW)
    assert result.intent.action == "recall"
    assert str(result.intent.start) == str(result.intent.end) == "2026-09-18"
