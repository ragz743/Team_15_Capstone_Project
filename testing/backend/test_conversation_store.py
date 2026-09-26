"""Verify persisted conversations without the API or model providers."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend.conversation_context import ConversationContext
from backend.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    TurnConflictError,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Opt-in local PostgreSQL persistence tests"
)


def test_restart_order_timestamp_and_context(database, store, completed):
    """A new repository instance and connection recover actual PostgreSQL records."""
    owner, token = store.create_owner()
    chat = store.create(owner)["id"]
    first = completed(store, owner, chat)
    second = completed(store, owner, chat, "What about humidity?", "45%")
    restarted = ConversationStore(database)
    assert restarted.owner(token) == owner
    saved = restarted.get(owner, chat)
    assert [m["request_id"] for m in saved["messages"]] == [first, first, second, second]
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "user", "assistant"]
    assert all(m["created_at"].utcoffset().total_seconds() == 0 for m in saved["messages"])
    assert saved["messages"] == store.get(owner, chat)["messages"]
    assert saved["context"]["start"] == "2026-09-10"
    assert saved["context"]["station_ids"] == ["1"]
    assert restarted.get(owner, store.create(owner)["id"])["context"] == ConversationContext().model_dump(mode="json")


def test_owner_isolation_for_every_read_and_write(store, completed):
    """A valid foreign UUID has the same result as a missing UUID."""
    owner, _ = store.create_owner()
    other, _ = store.create_owner()
    chat = store.create(owner)["id"]
    request = completed(store, owner, chat)
    assert store.list_conversations(other) == []
    for target in [chat, uuid4()]:
        with pytest.raises(ConversationNotFoundError):
            store.get(other, target)
        with pytest.raises(ConversationNotFoundError):
            store.begin(other, target, uuid4(), "Intrusion")
        with pytest.raises(ConversationNotFoundError):
            store.complete(other, target, request, uuid4(), "Intrusion", "fixture", ConversationContext())
    store.fail(other, chat, request, uuid4())
    assert store.get(owner, chat)["messages"][-1]["content"] == "72 F"
    assert store.owner("a" * 43) is None


def test_failure_retry_idempotency_and_concurrent_turns(store, database):
    """Retries do not duplicate questions and an old attempt cannot publish after replacement."""
    owner, _ = store.create_owner()
    chat = store.create(owner)["id"]
    request = uuid4()
    first = store.begin(owner, chat, request, "Humidity?")
    with pytest.raises(TurnConflictError):
        store.begin(owner, chat, uuid4(), "New turn during pending request")
    store.fail(owner, chat, request, first.attempt_id)
    assert len(store.get(owner, chat)["messages"]) == 1
    second = store.begin(owner, chat, request, "Humidity?")
    with pytest.raises(TurnConflictError):
        store.complete(owner, chat, request, first.attempt_id, "Stale answer", "fixture", ConversationContext())
    store.complete(owner, chat, request, second.attempt_id, "45%", "fixture", ConversationContext())
    assert store.begin(owner, chat, request, "Humidity?").completed["reply"] == "45%"
    assert len(store.get(owner, chat)["messages"]) == 2
    with pytest.raises(TurnConflictError):
        store.begin(owner, chat, request, "Changed question")
    expired = uuid4()
    stale = store.begin(owner, chat, expired, "Temperature?")
    with database() as conn:
        conn.execute(
            "UPDATE conversation_turns SET lease_until = now() - interval '1 second' WHERE request_id = %s", (expired,)
        )
    newer = store.begin(owner, chat, uuid4(), "Wind?")
    with pytest.raises(TurnConflictError):
        store.complete(owner, chat, expired, stale.attempt_id, "Stale", "fixture", ConversationContext())
    assert newer.context == ConversationContext()


def test_message_pagination_and_actual_concurrent_requests(store, completed):
    """Page boundaries preserve order and two simultaneous writers cannot append twice."""
    from concurrent.futures import ThreadPoolExecutor

    owner, _ = store.create_owner()
    chat = store.create(owner)["id"]
    for i in range(43):
        completed(store, owner, chat, f"Temperature question {i}")
    recent = store.get(owner, chat)
    older = store.get(owner, chat, before=recent["next_before"])
    messages = older["messages"] + recent["messages"]
    assert len(messages) == 86
    assert len({message["id"] for message in messages}) == 86
    assert messages[0]["content"] == "Temperature question 0"
    request = uuid4()

    def begin():
        try:
            return store.begin(owner, chat, request, "Concurrent question")
        except TurnConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: begin(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len([m for m in store.get(owner, chat)["messages"] if m["request_id"] == request]) == 1


def test_conversation_list_cursor_handles_equal_timestamps(store, database):
    """Equal timestamps must not make conversations disappear between pages."""
    owner, _ = store.create_owner()
    ids = {store.create(owner)["id"] for _ in range(53)}
    with database() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = %s WHERE owner_id = %s", (datetime(2026, 9, 10, tzinfo=UTC), owner)
        )
    first = store.list_conversations(owner)
    second = store.list_conversations(owner, before=first[-1]["updated_at"], before_id=first[-1]["id"])
    assert len(first) == 50 and len(second) == 3
    assert {chat["id"] for chat in first + second} == ids


def test_separate_process_recovers_persisted_messages(store, database, completed):
    """A fresh Python process can resume a conversation without any original process state."""
    import json
    import subprocess
    import sys

    owner, _ = store.create_owner()
    chat = store.create(owner)["id"]
    completed(store, owner, chat)
    with database() as conn:
        schema = conn.execute("SELECT current_schema()").fetchone()[0]
    program = """
import json, sys
from uuid import UUID
from psycopg import sql
from backend.databases.pgvector import PgVectorConnection
from backend.conversation_store import ConversationStore
schema, owner, chat = sys.argv[1:]
def connect():
    conn = PgVectorConnection(host="127.0.0.1", port=5432).conn
    conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
    conn.commit()
    return conn
saved = ConversationStore(connect).get(UUID(owner), UUID(chat))
print(json.dumps({"messages": [m["content"] for m in saved["messages"]], "context": saved["context"]}))
"""
    child = subprocess.run(
        [sys.executable, "-c", program, schema, str(owner), str(chat)],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    recovered = json.loads(child.stdout)
    assert recovered["messages"] == ["Temperature at Pullman on 2026-09-10", "72 F"]
    assert recovered["context"]["start"] == "2026-09-10"
