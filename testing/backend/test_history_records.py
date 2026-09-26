"""Saved history searches use owned records and stable request timestamps."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from backend.conversation_context import ConversationContext
from backend.conversation_store import ConversationNotFoundError

pytestmark = pytest.mark.skipif(os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Opt-in local PostgreSQL history checks")
SNAPSHOT_MIGRATION = Path(__file__).resolve().parents[2] / "deployment/migrations/002_turn_snapshots.sql"


def test_snapshot_upgrade_preserves_legacy_conversations(store, database, completed):
    """Upgrade rows with no snapshot fields without inventing input or source metadata."""
    owner, _ = store.create_owner()
    chat = store.create(owner)["id"]
    request = completed(store, owner, chat)
    before = store.get(owner, chat)
    with database() as conn:
        conn.execute(
            "ALTER TABLE conversation_turns DROP COLUMN request_input, "
            "DROP COLUMN prepared_turn, DROP COLUMN result_metadata"
        )
        conn.execute(SNAPSHOT_MIGRATION.read_bytes())
        conn.execute(SNAPSHOT_MIGRATION.read_bytes())
    assert store.get(owner, chat) == before
    replay = store.begin(owner, chat, request, "Temperature at Pullman on 2026-09-10")
    assert replay.prepared is None and replay.completed["reply"] == "72 F"


def test_history_search_topics_dates_current_scope_and_owner_isolation(store, database, completed):
    """Search sent dates and both message sides without crossing browser boundaries."""
    owner, _ = store.create_owner()
    foreign_owner, _ = store.create_owner()
    old, current = store.create(owner)["id"], store.create(owner)["id"]
    foreign = store.create(foreign_owner)["id"]
    frost = completed(store, owner, old, "Did my crops get cold on January 1?", "We discussed freezing and frost.")
    completed(store, foreign_owner, foreign, "Foreign frost secret", "PRIVATE")
    now = datetime.now(UTC)
    with database() as conn:
        conn.execute(
            "UPDATE conversation_turns SET requested_at = %s, completed_at = %s WHERE request_id = %s",
            (datetime(2026, 9, 11, 6, 30, tzinfo=UTC), datetime(2026, 9, 11, 6, 31, tzinfo=UTC), frost),
        )
    rows = store.search_history(
        owner,
        current,
        before=now,
        scope="all",
        terms=["frost", "freezing"],
        start=datetime(2026, 9, 10, 7, tzinfo=UTC),
        end=datetime(2026, 9, 11, 7, tzinfo=UTC),
    )
    assert len(rows) == 1 and rows[0]["conversation_id"] == old
    assert "January 1" in rows[0]["user_content"]
    assert store.search_history(owner, current, before=now, scope="current", terms=["frost"]) == []
    completed(store, owner, current, "Frost here too?", "The current chat reply")
    rows = store.search_history(owner, current, before=datetime.now(UTC), scope="current", terms=["frost"])
    assert len(rows) == 1 and rows[0]["conversation_id"] == current
    for method in [
        lambda: store.search_history(foreign_owner, current, before=now, scope="all", terms=[]),
        lambda: store.history_window(foreign_owner, current, before=now),
    ]:
        with pytest.raises(ConversationNotFoundError):
            method()


def test_history_acceptance_cutoff_ignores_later_messages_and_completions(store, database, completed):
    """A retry cannot see messages or assistant replies that arrived after acceptance."""
    owner, _ = store.create_owner()
    old, current = store.create(owner)["id"], store.create(owner)["id"]
    request = uuid4()
    accepted = store.begin(owner, old, request, "Frost question before the cutoff")
    with database() as conn:
        cutoff = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    store.complete(owner, old, request, accepted.attempt_id, "Reply after the cutoff", "fixture", ConversationContext())
    completed(store, owner, old, "Question after cutoff", "Later")
    rows = store.search_history(owner, current, before=cutoff, scope="previous", terms=[])
    assert len(rows) == 1 and rows[0]["assistant_content"] is None
    assert store.search_history(owner, current, before=cutoff, scope="all", terms=["Reply after"]) == []
    window = store.history_window(owner, old, before=cutoff)
    assert len(window) == 1 and window[0]["assistant"] == ""


def test_history_limits_literal_terms_and_failed_questions(store, completed):
    """Bound large results; SQL/wildcard-like topics are literal text, not a widened search."""
    owner, _ = store.create_owner()
    old, current = store.create(owner)["id"], store.create(owner)["id"]
    for index in range(15):
        completed(store, owner, old, f"Frost discussion {index}", "Saved answer")
    failed = uuid4()
    accepted = store.begin(owner, old, failed, "Frost question with no answer")
    store.fail(owner, old, failed, accepted.attempt_id)
    rows = store.search_history(owner, current, before=datetime.now(UTC), scope="all", terms=["frost"])
    assert len(rows) == 13 and rows[0]["assistant_content"] is None
    for term in ["%", "_", "' OR true --"]:
        assert store.search_history(owner, current, before=datetime.now(UTC), scope="all", terms=[term]) == []
