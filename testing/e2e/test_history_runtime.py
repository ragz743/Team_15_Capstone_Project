"""Opt-in real history model and API check in a disposable local database schema."""

import os
from pathlib import Path
from uuid import UUID, uuid4

import backend.api as api
import dotenv
import pytest
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.conversation_store import ConversationStore
from backend.databases.pgvector import PgVectorConnection
from backend.history_service import HistoryService
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from fastapi.testclient import TestClient
from psycopg import sql

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HISTORY_RUNTIME_TESTS") != "1", reason="Opt-in local PostgreSQL and external history model check"
)


@pytest.fixture
def history_runtime(monkeypatch):
    """Use the real saved-chat route, isolated persistence and an explicitly selected free model."""
    dotenv.load_dotenv()
    model_name = os.environ["OPENROUTER_HISTORY_MODEL"]
    assert model_name.endswith(":free"), "This check only authorizes a free history model"
    schema = "test_history_runtime_" + uuid4().hex

    def connect():
        conn = PgVectorConnection(host="127.0.0.1", port=5432, connect_timeout=5).conn
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.commit()
        return conn

    migrations = Path(__file__).resolve().parents[2] / "deployment/migrations"
    with connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for migration in sorted(migrations.glob("*.sql")):
            conn.execute(migration.read_bytes())
    try:
        model = ChatbotOpenRouter(
            {"model": model_name, "temperature": 0, "max_tokens": 1800, "request_timeout": 25000, "max_retries": 0}
        )
        calls = []
        invoke_json = model.invoke_json

        def counted(instructions, payload, output_schema):
            calls.append(output_schema.get("title"))
            return invoke_json(instructions, payload, output_schema)

        monkeypatch.setattr(model, "invoke_json", counted)
        monkeypatch.setattr(api, "_conversations", ConversationStore(connect))
        monkeypatch.setattr(api, "_history_service", HistoryService(model, model_name))
        monkeypatch.setattr(api, "_retriever", None)
        yield connect, calls
    finally:
        with connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_live_history_recall_reload_replay_and_isolation(history_runtime, monkeypatch):
    """Recall synthetic history through the real model, then reload and replay without model calls."""
    connect, calls = history_runtime
    store = api._conversations
    client = TestClient(api.app)
    old = UUID(client.post("/api/conversations").json()["id"])
    owner = store.owner(client.cookies.get("awn_browser"))
    assert owner is not None
    request = uuid4()
    accepted = store.begin(owner, old, request, "Did frost affect my Pullman crops in January?")
    store.complete(
        owner,
        old,
        request,
        accepted.attempt_id,
        "No matching January observations were available. I could not confirm frost.",
        "synthetic-history",
        ConversationContext(),
    )
    other, _ = store.create_owner()
    foreign = store.create(other)["id"]
    foreign_request = uuid4()
    foreign_turn = store.begin(other, foreign, foreign_request, "PRIVATE_OTHER_BROWSER_FROST")
    store.complete(
        other, foreign, foreign_request, foreign_turn.attempt_id, "PRIVATE_SECRET", "fixture", ConversationContext()
    )
    current = client.post("/api/conversations").json()["id"]
    day = accepted.requested_at.astimezone(TIMEZONE).strftime("%B %d, %Y")
    payload = {
        "conversation_id": current,
        "request_id": str(uuid4()),
        "message": f"Can you bring back that freezing discussion we had about my crops on {day}?",
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, f"History runtime status {response.status_code}: {response.text}"
    body = response.json()
    assert body["outcome"] == "history" and "[1]" in body["reply"]
    assert "could not confirm frost" in body["reply"] and "PRIVATE_SECRET" not in body["reply"]
    assert accepted.requested_at.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M %Z") in body["reply"]
    assert "not updated weather" in body["reply"]
    assert body["context"]["station_ids"] == []
    completed_calls = len(calls)
    assert completed_calls >= 2
    monkeypatch.setattr(api, "_conversations", ConversationStore(connect))
    reopened = TestClient(api.app, cookies=client.cookies)
    saved = reopened.get(f"/api/conversations/{current}").json()
    assert saved["messages"][-1]["content"] == body["reply"]
    assert reopened.post("/api/chat", json=payload).json() == body
    assert len(calls) == completed_calls
    stranger = TestClient(api.app)
    assert stranger.get(f"/api/conversations/{current}").status_code == 404
    client.close()
    reopened.close()
    stranger.close()
