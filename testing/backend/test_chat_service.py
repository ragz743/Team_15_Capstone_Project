"""Provider errors and replay behavior at the saved chat boundary."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import backend.api as api
import pytest
from backend.chat_turn import PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.conversation_store import AcceptedTurn
from backend.history_models import HistoryIntent, HistorySnapshot
from backend.history_service import HistoryResolution
from backend.weather_query import WeatherQuery
from fastapi.testclient import TestClient


@pytest.mark.parametrize("operation", ["interpret_history", "answer_history", "prepare_weather", "answer_weather"])
def test_failures_keep_their_operation_and_record_the_failed_attempt(monkeypatch, operation):
    """A history provider error must not be reported as weather retrieval failing."""
    store, history, weather = MagicMock(), MagicMock(), MagicMock()
    turn = AcceptedTurn(uuid4(), ConversationContext())
    store.begin.return_value = turn
    history.prepare.return_value = HistoryResolution(HistoryIntent(action="weather"))
    if operation == "interpret_history":
        history.prepare.side_effect = RuntimeError("private provider detail")
    elif operation == "answer_history":
        history.prepare.return_value = HistoryResolution(
            HistoryIntent(action="recall"),
            snapshot=HistorySnapshot(intent=HistoryIntent(action="recall"), as_of=turn.requested_at, entries=[]),
        )
        history.answer.side_effect = RuntimeError("private provider detail")
    elif operation == "prepare_weather":
        weather.prepare_turn.side_effect = RuntimeError("private provider detail")
    else:
        day = date(2026, 9, 9)
        context = ConversationContext(station_ids=["1"], start=day, end=day, subject="wind")
        weather.prepare_turn.return_value = PreparedChatTurn(
            outcome="weather",
            question="Weather?",
            context=context,
            selection=WeatherQuery(("1",), day, day),
        )
        weather.answer_result.side_effect = RuntimeError("private provider detail")
    monkeypatch.setattr(api, "_conversations", store)
    monkeypatch.setattr(api, "_history_service", history)
    monkeypatch.setattr(api, "_retriever", weather)
    result = TestClient(api.app).post(
        "/api/chat",
        json={
            "conversation_id": str(uuid4()),
            "request_id": str(uuid4()),
            "message": "Weather?",
        },
    )
    assert result.status_code == 502
    assert "private provider" not in result.text
    assert ("Saved conversation" in result.text) == ("history" in operation)
    store.fail.assert_called_once()
    store.complete.assert_not_called()


def test_completed_legacy_turn_replays_without_providers(monkeypatch):
    """Results written before outcome metadata existed remain readable and idempotent."""
    store = MagicMock()
    store.begin.return_value = AcceptedTurn(
        uuid4(), ConversationContext(), {"reply": "Original answer", "model": "old"}
    )
    monkeypatch.setattr(api, "_conversations", store)
    monkeypatch.setattr(api, "_history_service", None)
    monkeypatch.setattr(api, "_retriever", None)
    payload = {"conversation_id": str(uuid4()), "request_id": str(uuid4()), "message": "Old question"}
    response = TestClient(api.app).post("/api/chat", json=payload)
    assert response.status_code == 200
    assert response.json()["reply"] == "Original answer" and response.json()["outcome"] == "success"
    store.prepare.assert_not_called()
    store.complete.assert_not_called()
