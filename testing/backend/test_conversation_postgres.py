"""Opt-in persistence tests in a unique schema on the local Compose PostgreSQL service."""

import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime
from itertools import cycle
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import backend.api as api
import pytest
from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.conversation_store import (
    ConversationStore,
)
from backend.history_service import HistoryService
from backend.weather_query import RequestedPoint, Station, WeatherQuery
from backend.workflow.engine import LangGraphEngine
from fastapi.testclient import TestClient
from history_fixture import FixtureHistoryModel, structured_mock
from weather_fixtures import POINT, STATION
from workflow_fixture import make_graph

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Opt-in local PostgreSQL persistence tests"
)
MIGRATION = Path(__file__).resolve().parents[2] / "deployment/migrations/001_conversations.sql"
SNAPSHOT_MIGRATION = MIGRATION.with_name("002_turn_snapshots.sql")


@pytest.fixture(autouse=True)
def history_model(monkeypatch):
    """Use the real history path with scripted model outputs, never external providers."""
    monkeypatch.setattr(api, "_history_service", HistoryService(FixtureHistoryModel(), "fixture-history"))


class FixtureRetriever:
    """Deterministic weather retrieval retaining the last received context."""

    def __init__(self):
        """Initialize call tracking."""
        self.calls = []
        self.fail = False

    def stations(self):
        """Provide the public identity used to label a resolved conversation."""
        return [Station("1", "Pullman", "Whitman")]

    def prepare_turn(self, question, context=None, *, reference_time=None, point=None, history=None):
        """Supply fixed constraints for tests focused on persistence and ownership."""
        context = (
            context
            if context and context.station_ids
            else ConversationContext(
                point=point, station_ids=["1"], start=date(2026, 9, 10), end=date(2026, 9, 10), subject="humidity"
            )
        )
        assert context.start is not None and context.end is not None
        return PreparedChatTurn(
            outcome="weather",
            question=question,
            context=context,
            selection=WeatherQuery(tuple(context.station_ids), context.start, context.end, context.county),
        )

    def answer_result(self, turn):
        """Return a fixed answer or an external-service failure."""
        self.calls.append((turn.question, turn.context))
        if self.fail:
            raise RuntimeError("private provider detail")
        return AnsweredTurn(reply="Fresh retrieved weather", outcome="success")


def test_http_cookie_reload_retry_and_ownership(store, database, monkeypatch):
    """Separate browser sessions cannot access each other's saved chats."""
    monkeypatch.setattr(api, "_conversations", store)
    retriever = FixtureRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    client = TestClient(api.app)
    other = TestClient(api.app)
    response = client.post("/api/conversations")
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api" in cookie
    chat = response.json()["id"]
    request = str(uuid4())
    payload = {"conversation_id": chat, "request_id": request, "message": "Humidity?"}
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 200
    assert client.post("/api/chat", json=payload).json() == first.json()
    assert len(retriever.calls) == 1
    monkeypatch.setattr(api, "_conversations", ConversationStore(database))
    reloaded = TestClient(api.app)
    reloaded.cookies.update(client.cookies)
    assert len(reloaded.get(f"/api/conversations/{chat}").json()["messages"]) == 2
    other.get("/api/conversations")
    for target in [chat, str(uuid4())]:
        assert other.get(f"/api/conversations/{target}").json() == {"detail": "Conversation not found."}
        assert other.post("/api/chat", json={**payload, "conversation_id": target}).status_code == 404
    assert client.post("/api/chat", json={**payload, "user_id": str(uuid4())}).status_code == 422
    assert client.post("/api/chat", json={**payload, "context": {}}).status_code == 422
    assert client.post("/api/conversations", headers={"Origin": "https://foreign.example"}).status_code == 403
    retriever.fail = True
    failed_payload = {**payload, "request_id": str(uuid4()), "message": "Temperature?"}
    failure = client.post("/api/chat", json=failed_payload)
    assert failure.status_code == 502 and "private provider" not in failure.text
    saved = client.get(f"/api/conversations/{chat}").json()
    assert saved["messages"][-1]["role"] == "user" and saved["messages"][-1]["status"] == "failed"
    retriever.fail = False
    assert client.post("/api/chat", json=failed_payload).status_code == 200
    assert len(client.get(f"/api/conversations/{chat}").json()["messages"]) == 4


def test_explicit_history_cannot_trigger_new_weather(store, monkeypatch, completed):
    """An old assistant claim can be quoted as history but cannot supply new weather evidence."""
    monkeypatch.setattr(api, "_conversations", store)
    client = TestClient(api.app)
    old = UUID(client.post("/api/conversations").json()["id"])
    owner = store.owner(client.cookies.get("awn_browser"))
    completed(store, owner, old, "Frost at Pullman on 2026-09-10?", "OLD CLAIM: 999 degrees")
    current = client.post("/api/conversations").json()["id"]
    monkeypatch.setattr(api, "_retriever", None)
    recalled = client.post(
        "/api/chat",
        json={
            "conversation_id": current,
            "request_id": str(uuid4()),
            "message": "What did we discuss last time?",
            "mode": "history",
        },
    )
    assert recalled.status_code == 200 and "OLD CLAIM" in recalled.json()["reply"]
    retriever = FixtureRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    result = client.post(
        "/api/chat",
        json={
            "conversation_id": current,
            "request_id": str(uuid4()),
            "message": "Using our last conversation, what about humidity?",
            "mode": "history",
        },
    )
    assert result.status_code == 200 and result.json()["outcome"] == "needs_clarification"
    assert not retriever.calls


def test_secure_cookie_and_cors_configuration(store, monkeypatch):
    """HTTPS identities are secure and only explicitly allowed origins receive credentialed CORS."""
    monkeypatch.setattr(api, "_conversations", store)
    client = TestClient(api.app, base_url="https://testserver")
    response = client.post("/api/conversations")
    assert "Secure" in response.headers["set-cookie"]
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    response = client.options("/api/chat", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    headers["Origin"] = "https://foreign.example"
    assert client.options("/api/chat", headers=headers).status_code == 400


def graph_weather(monkeypatch):
    """Run the real weather graph with controlled provider and source replies."""
    runtime = make_graph(monkeypatch)
    directory = MagicMock()
    directory.stations.return_value = [STATION, replace(STATION, id="2", name="Colfax", latitude="46.88")]
    engine = LangGraphEngine(runtime.model, runtime.classifier, directory=directory)
    monkeypatch.setattr(api, "_retriever", engine)
    return runtime


def test_saved_weather_retry_keeps_original_date_after_provider_failure(store, database, monkeypatch):
    """Retry the frozen graph inputs across a provider failure and a server restart."""
    monkeypatch.setattr(api, "_conversations", store)
    runtime = graph_weather(monkeypatch)
    client = TestClient(api.app)
    chat = UUID(client.post("/api/conversations").json()["id"])
    owner = store.owner(client.cookies.get("awn_browser"))
    request = uuid4()
    question = "Temperature at Pullman yesterday"
    first = store.begin(owner, chat, request, question, request_input={"point": POINT.model_dump()})
    store.fail(owner, chat, request, first.attempt_id)
    accepted = datetime(2026, 9, 11, 6, 59, tzinfo=UTC)
    with database() as conn:
        conn.execute("UPDATE conversation_turns SET requested_at = %s WHERE request_id = %s", (accepted, request))
    payload = {
        "conversation_id": str(chat),
        "request_id": str(request),
        "message": question,
        "point": POINT.model_dump(),
    }
    runtime.classifier.invoke_json.side_effect = RuntimeError("private provider failure")
    failure = client.post("/api/chat", json=payload)
    assert failure.status_code == 502 and "private" not in failure.text
    runtime.classifier.invoke_json.side_effect = None
    monkeypatch.setattr(api, "_conversations", ConversationStore(database))
    reply = client.post("/api/chat", json=payload)
    assert reply.status_code == 200, reply.text
    supplied = runtime.classifier.invoke_json.call_args.args[1]
    assert datetime.fromisoformat(supplied["reference_time"]) == accepted
    saved = store.get(owner, chat)["messages"]
    assert len(saved) == 2
    assert saved[-1]["metadata"]["sources"] == reply.json()["sources"]
    assert reply.json()["sources"][0]["station"] == "Pullman"
    assert reply.json()["coverage"] == "subset"
    assert client.post("/api/chat", json=payload).json() == reply.json()
    assert runtime.model.invoke.call_count == 2


def test_saved_weather_followup_chain_uses_fresh_evidence_after_reopening(store, database, monkeypatch):
    """Keep selected points and dated recent questions across saved followups."""
    monkeypatch.setattr(api, "_conversations", store)
    runtime = graph_weather(monkeypatch)
    runtime.model.invoke.side_effect = cycle(
        [
            "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29'",
            "The selected source reported 70.25 F.",
        ]
    )
    second_point = RequestedPoint(latitude=46.88, longitude=-117.181)
    client = TestClient(api.app)
    chat = client.post("/api/conversations").json()["id"]
    questions = ["Temperature yesterday?", "And humidity?", "Same at this point?"]
    for index, question in enumerate(questions):
        point = second_point if index == 2 else POINT
        if index == 2:
            monkeypatch.setattr(api, "_conversations", ConversationStore(database))
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": chat,
                "request_id": str(uuid4()),
                "message": question,
                "point": point.model_dump(),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["context"]["station_ids"] == (["2"] if index == 2 else ["1"])
        supplied = runtime.classifier.invoke_json.call_args.args[1]
        assert supplied["question"] == question
        assert [item["user"] for item in supplied["history"]] == questions[:index]
        assert all(item["asked_at"] for item in supplied["history"])
    assert runtime.cursor.execute.call_count == 3


def test_llm_history_http_reload_same_chat_and_browser_isolation(store, database, monkeypatch, completed):
    """The full API interprets a paraphrase, recalls real records and survives a new session."""
    monkeypatch.setattr(api, "_conversations", store)
    monkeypatch.setattr(api, "_retriever", None)
    client = TestClient(api.app)
    old = UUID(client.post("/api/conversations").json()["id"])
    owner = store.owner(client.cookies.get("awn_browser"))
    completed(store, owner, old, "Did frost affect Pullman in January?", "Saved frost discussion only.")
    stranger, _ = store.create_owner()
    completed(store, stranger, store.create(stranger)["id"], "Frost SECRET_OTHER_BROWSER", "PRIVATE_SECRET")
    model = structured_mock(MagicMock())
    model.invoke.side_effect = [
        json.dumps({"action": "recall", "terms": ["frost", "freezing"]}),
        json.dumps({"statements": [{"text": "Your earlier question concerned frost at Pullman.", "refs": [1]}]}),
    ]
    monkeypatch.setattr(api, "_history_service", HistoryService(model, "fixture-history"))
    # Reopen using the same credential, like returning to the app in another session.
    restarted = TestClient(api.app)
    restarted.cookies.update(client.cookies)
    monkeypatch.setattr(api, "_conversations", ConversationStore(database))
    current = restarted.post("/api/conversations").json()["id"]
    payload = {
        "conversation_id": current,
        "mode": "history",
        "request_id": str(uuid4()),
        "message": "that icy crop chat, remind me?",
    }
    response = restarted.post("/api/chat", json=payload)
    assert response.status_code == 200 and response.json()["outcome"] == "history"
    assert "Saved frost discussion only" in response.json()["reply"]
    assert "PRIVATE_SECRET" not in str(model.invoke.call_args_list)
    assert "SECRET_OTHER_BROWSER" not in str(model.invoke.call_args_list)
    assert restarted.post("/api/chat", json=payload).json() == response.json()
    assert model.invoke.call_count == 2
    saved = restarted.get(f"/api/conversations/{current}").json()
    assert saved["messages"][-1]["content"] == response.json()["reply"]
    assert TestClient(api.app).get(f"/api/conversations/{current}").status_code == 404


def test_history_answer_retry_uses_frozen_evidence_after_restart(store, database, monkeypatch, completed):
    """A failed summary retains its exact evidence and does not reinterpret or re-search."""
    monkeypatch.setattr(api, "_conversations", store)
    monkeypatch.setattr(api, "_retriever", None)
    client = TestClient(api.app)
    old = UUID(client.post("/api/conversations").json()["id"])
    owner = store.owner(client.cookies.get("awn_browser"))
    completed(store, owner, old, "Frost original question", "ORIGINAL_SAVED_REPLY")
    current = client.post("/api/conversations").json()["id"]
    model = structured_mock(MagicMock())
    model.invoke.side_effect = [
        '{"action":"recall","terms":["frost"]}',
        TimeoutError("private failure"),
        '{"statements":[{"text":"You discussed frost.","refs":[1]}]}',
    ]
    monkeypatch.setattr(api, "_history_service", HistoryService(model, "fixture-history"))
    payload = {
        "conversation_id": current,
        "mode": "history",
        "request_id": str(uuid4()),
        "message": "Remember the frost chat?",
    }
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 502 and "private failure" not in first.text
    completed(store, owner, old, "Frost arrived after the request", "LATER_REPLY")
    restarted = ConversationStore(database)
    monkeypatch.setattr(api, "_conversations", restarted)
    monkeypatch.setattr(restarted, "history_window", MagicMock(side_effect=AssertionError("reinterpreted")))
    monkeypatch.setattr(restarted, "search_history", MagicMock(side_effect=AssertionError("re-searched")))
    result = client.post("/api/chat", json=payload)
    assert result.status_code == 200 and "ORIGINAL_SAVED_REPLY" in result.json()["reply"]
    assert "LATER_REPLY" not in result.text and "LATER_REPLY" not in model.invoke.call_args.args[0][0]
    assert client.post("/api/chat", json=payload).json() == result.json()
    assert model.invoke.call_count == 3


def test_history_clarification_context_and_service_failures(store, monkeypatch):
    """An unresolved history date is clarified once and the short answer reaches the model."""
    monkeypatch.setattr(api, "_conversations", store)
    client = TestClient(api.app)
    current = client.post("/api/conversations").json()["id"]
    model = structured_mock(MagicMock())
    model.invoke.side_effect = [
        '{"action":"clarify","clarification":"Which September did you mean?"}',
        '{"action":"recall","start":"2025-09-01","end":"2025-09-30"}',
    ]
    monkeypatch.setattr(api, "_history_service", HistoryService(model, "fixture-history"))
    result = client.post(
        "/api/chat",
        json={
            "conversation_id": current,
            "mode": "history",
            "request_id": str(uuid4()),
            "message": "Our September chats?",
        },
    )
    assert result.json()["outcome"] == "needs_clarification"
    result = client.post(
        "/api/chat", json={"conversation_id": current, "mode": "history", "request_id": str(uuid4()), "message": "2025"}
    )
    assert result.status_code == 200 and "could not find" in result.json()["reply"]
    assert "Which September did you mean?" in model.invoke.call_args.args[0][0]
    assert '"message": "2025"' in model.invoke.call_args.args[0][0]
    monkeypatch.setattr(api, "_history_service", None)
    result = client.post(
        "/api/chat",
        json={"conversation_id": current, "mode": "history", "request_id": str(uuid4()), "message": "Remember?"},
    )
    assert result.status_code == 503


def test_changed_map_point_conflicts_with_original_request(store, monkeypatch):
    """Retries cannot move the source even when the original request already completed."""
    monkeypatch.setattr(api, "_conversations", store)
    retriever = FixtureRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    client = TestClient(api.app)
    chat = client.post("/api/conversations").json()["id"]
    payload = {"conversation_id": chat, "request_id": str(uuid4()), "message": "Wind?", "point": POINT.model_dump()}
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 200
    assert client.post("/api/chat", json=payload).json() == first.json()
    changed = {**payload, "point": {"latitude": 47.0, "longitude": -120.0}}
    assert client.post("/api/chat", json=changed).status_code == 409
    assert len(retriever.calls) == 1
    assert client.post("/api/chat", json={**payload, "mode": "history"}).status_code == 409
    restored = client.get(f"/api/conversations/{chat}").json()
    assert restored["messages"][0]["request_input"] == {"point": POINT.model_dump()}


@pytest.mark.parametrize("failure", ["classification", "no_data", "provider"])
def test_saved_graph_failures_and_missing_observations(store, monkeypatch, failure):
    """Exercise failure responses and persisted outcomes through the saved HTTP path."""
    monkeypatch.setattr(api, "_conversations", store)
    monkeypatch.setattr(api, "_history_service", None)
    runtime = graph_weather(monkeypatch)
    if failure == "classification":
        runtime.classifier.invoke_json.return_value = "invalid"
    elif failure == "no_data":
        runtime.cursor.fetchall.return_value = []
    else:
        runtime.classifier.invoke_json.side_effect = RuntimeError("private provider details")
    client = TestClient(api.app)
    chat = client.post("/api/conversations").json()["id"]
    payload = {
        "conversation_id": chat,
        "request_id": str(uuid4()),
        "message": "Temperature?",
        "point": POINT.model_dump(),
    }
    result = client.post("/api/chat", json=payload)
    saved = client.get(f"/api/conversations/{chat}").json()["messages"]
    if failure == "no_data":
        assert result.status_code == 200 and result.json()["outcome"] == "no_data"
        assert saved[-1]["role"] == "assistant"
        assert client.post("/api/chat", json=payload).json() == result.json()
        assert runtime.model.invoke.call_count == 1
    else:
        assert result.status_code == 502 and saved[-1]["status"] == "failed"
        assert "private" not in result.text
        if failure == "classification":
            assert "interpret your question" in result.json()["detail"]
        assert runtime.classifier.invoke_json.call_count == (2 if failure == "classification" else 1)
        runtime.cursor.execute.assert_not_called()
