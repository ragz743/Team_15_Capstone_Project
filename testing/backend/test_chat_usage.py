"""Meter saved chat attempts without charging replayed or rejected turns."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import backend.api as api
import httpx
import pytest
from backend.analytics.usage_store import UsageTracker
from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.conversation_store import AcceptedTurn, ConversationNotFoundError, TurnConflictError
from backend.history_service import HistoryService
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.workflow.contracts import WorkflowRequest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from openai import RateLimitError


def model_reply(text="72 F"):
    """Represent provider-reported tokens and billed cost without contacting a provider."""
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        response_metadata={"model_name": "paid/weather", "cost": 0.002},
    )


@pytest.fixture
def chat_usage(monkeypatch):
    """Exercise the real request tracker and saved-chat service with replaceable storage."""
    recorder, conversations, weather = MagicMock(), MagicMock(), MagicMock()
    turn = AcceptedTurn(uuid4(), ConversationContext(station_ids=["1"]))
    conversations.begin.return_value = turn
    weather.prepare_turn.return_value = PreparedChatTurn(
        question="Weather?",
        outcome="weather",
        context=turn.context,
        workflow=WorkflowRequest(station_id="1", reference_time=turn.requested_at),
    )
    model = GenericFakeChatModel(messages=iter([model_reply()]))
    weather.answer_result.side_effect = lambda _: AnsweredTurn(
        reply=str(model.invoke(["Weather?"]).content), outcome="success"
    )
    monkeypatch.setattr(api, "_conversations", conversations)
    monkeypatch.setattr(api, "_retriever", weather)
    monkeypatch.setattr(api, "_usage_tracker", UsageTracker(recorder))
    payload = {"conversation_id": str(uuid4()), "request_id": str(uuid4()), "message": "Weather?"}
    return SimpleNamespace(
        recorder=recorder,
        conversations=conversations,
        weather=weather,
        turn=turn,
        payload=payload,
        client=TestClient(api.app),
        headers={"X-AWN-User-Id": "sai@wsu.edu", "X-AWN-Session-Id": "login-1"},
    )


def test_saved_chat_records_provider_usage_and_does_not_count_replay(chat_usage):
    """One generated answer and any number of completed retries count as one call."""
    f = chat_usage
    response = f.client.post("/api/chat", json=f.payload, headers=f.headers)
    assert response.status_code == 200
    usage = f.recorder.record.call_args.args[0]
    assert (usage.user_id, usage.session_id, usage.status) == ("sai@wsu.edu", "login-1", "ok")
    [call] = usage.calls
    assert (call.input_tokens, call.output_tokens, call.cost_usd) == (100, 10, 0.002)
    assert not call.tokens_estimated

    f.conversations.begin.return_value = AcceptedTurn(uuid4(), f.turn.context, response.json())
    replay = f.client.post("/api/chat", json=f.payload, headers=f.headers)
    assert replay.json() == response.json()
    assert "replayed" not in replay.json()
    f.recorder.record.assert_called_once()
    f.weather.answer_result.assert_called_once()


@pytest.mark.parametrize("reason", ["unavailable", "empty", "rate_limited", "error"])
def test_saved_failures_keep_their_status_and_original_error(chat_usage, monkeypatch, reason):
    """Dashboard outcomes match errors returned by the saved weather path."""
    f = chat_usage
    if reason == "unavailable":
        monkeypatch.setattr(api, "_retriever", None)
    elif reason == "empty":
        f.weather.answer_result.side_effect = lambda _: AnsweredTurn(reply=" ", outcome="success")
    elif reason == "rate_limited":
        f.weather.answer_result.side_effect = RateLimitError(
            "private error",
            response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")),
            body=None,
        )
    else:
        f.weather.answer_result.side_effect = RuntimeError("private error")
    response = f.client.post("/api/chat", json=f.payload)
    assert response.status_code == (503 if reason in ("unavailable", "rate_limited") else 502)
    usage = f.recorder.record.call_args.args[0]
    assert usage.status == reason
    assert "private error" not in response.text
    if reason == "rate_limited":
        assert usage.error_type == "RateLimitError"


@pytest.mark.parametrize("error", [ConversationNotFoundError(), TurnConflictError("Already running")])
def test_rejected_saved_turn_does_not_count_as_a_call(chat_usage, error):
    """A foreign conversation or concurrent duplicate cannot add model usage."""
    f = chat_usage
    f.conversations.begin.side_effect = error
    assert f.client.post("/api/chat", json=f.payload).status_code in (404, 409)
    f.recorder.record.assert_not_called()
    f.weather.answer_result.assert_not_called()


def test_model_cost_survives_a_later_persistence_failure(chat_usage):
    """An answer billed by the provider still costs money when saving the answer fails."""
    f = chat_usage
    f.conversations.complete.side_effect = TurnConflictError("Attempt expired")
    assert f.client.post("/api/chat", json=f.payload).status_code == 409
    usage = f.recorder.record.call_args.args[0]
    assert usage.status == "error" and len(usage.calls) == 1
    assert usage.calls[0].cost_usd == 0.002


def test_history_interpretation_is_metered_through_the_production_model_wrapper(chat_usage, monkeypatch):
    """Structured history calls retain usage even when there are no matching saved messages."""
    f = chat_usage
    model = object.__new__(ChatbotOpenRouter)
    model._model = GenericFakeChatModel(messages=iter([model_reply(json.dumps({"action": "recall"}))]))
    f.conversations.history_window.return_value = []
    f.conversations.search_history.return_value = []
    monkeypatch.setattr(api, "_history_service", HistoryService(model, "paid/history"))
    response = f.client.post("/api/chat", json={**f.payload, "mode": "history"}, headers=f.headers)
    assert response.status_code == 200 and response.json()["outcome"] == "history"
    usage = f.recorder.record.call_args.args[0]
    assert usage.status == "ok" and len(usage.calls) == 1
    f.weather.answer_result.assert_not_called()


def test_session_header_without_a_user_does_not_invent_a_login(chat_usage):
    """Browser-only callers still contribute spending without creating signed-in users or sessions."""
    f = chat_usage
    assert f.client.post("/api/chat", json=f.payload, headers={"X-AWN-Session-Id": "orphan"}).status_code == 200
    usage = f.recorder.record.call_args.args[0]
    assert usage.user_id is None and usage.session_id is None and len(usage.calls) == 1


def test_sql_workflow_does_not_publish_an_index_quality_score(monkeypatch):
    """An incompatible sampler must not publish a fabricated zero or success rate."""
    monkeypatch.setattr(api, "_retriever", SimpleNamespace())
    store = MagicMock()
    api._check_quality_if_due(store)
    store.record_quality_run.assert_not_called()
    store.latest_quality_run_at.assert_not_called()
