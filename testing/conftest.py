"""Disposable PostgreSQL storage and saved conversation fixtures."""

from datetime import date
from pathlib import Path
from uuid import uuid4

import dotenv
import pytest
from backend.conversation_context import ConversationContext
from backend.conversation_store import ConversationStore
from backend.databases.pgvector import PgVectorConnection
from psycopg import sql

MIGRATION = Path(__file__).resolve().parents[1] / "deployment/migrations/001_conversations.sql"
SNAPSHOT_MIGRATION = MIGRATION.with_name("002_turn_snapshots.sql")


@pytest.fixture
def database():
    """Create only a uniquely named test schema, leaving all weather data untouched."""
    dotenv.load_dotenv()
    schema = "test_conversations_" + uuid4().hex

    def connect():
        connection = PgVectorConnection(host="127.0.0.1", port=5432).conn
        connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        connection.commit()
        return connection

    with connect() as conn:
        assert conn.info.dbname == "vectorstore"
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(MIGRATION.read_bytes())
        conn.execute(SNAPSHOT_MIGRATION.read_bytes())
    try:
        yield connect
    finally:
        with connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def store(database):
    """Return a store whose every transaction uses the isolated schema."""
    return ConversationStore(database)


@pytest.fixture
def completed():
    """Provide a helper for persisting completed turns through the storage layer."""

    def save(store, owner, chat, question="Temperature at Pullman on 2026-09-10", reply="72 F", context=None):
        """Store a real completed turn using the production transaction paths."""
        request = uuid4()
        turn = store.begin(owner, chat, request, question)
        context = context or ConversationContext(
            station_ids=["1"], start=date(2026, 9, 10), end=date(2026, 9, 10), subject="temperature"
        )
        store.complete(owner, chat, request, turn.attempt_id, reply, "fixture", context)
        return request

    return save
