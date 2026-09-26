"""Conversation schema checks independent of chat services and model providers."""

import os
from pathlib import Path
from uuid import uuid4

import dotenv
import pytest
from backend.databases.pgvector import PgVectorConnection
from psycopg import sql

pytestmark = pytest.mark.skipif(os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Opt-in local PostgreSQL checks")
MIGRATION = Path(__file__).resolve().parents[2] / "deployment/migrations/001_conversations.sql"
SNAPSHOT_MIGRATION = MIGRATION.with_name("002_turn_snapshots.sql")


@pytest.fixture
def database():
    """Create an empty disposable schema without modifying existing weather or history."""
    dotenv.load_dotenv()
    schema = "test_history_migrations_" + uuid4().hex

    def connect():
        conn = PgVectorConnection(host="127.0.0.1", port=5432).conn
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.commit()
        return conn

    with connect() as conn:
        assert conn.info.dbname == "vectorstore"
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield connect
    finally:
        with connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_migration_is_idempotent_and_preserves_existing_weather(database):
    """An upgrade may add history tables but cannot rewrite existing weather records."""
    with database() as conn:
        conn.execute("CREATE TABLE daily_index (id integer, document text)")
        conn.execute("INSERT INTO daily_index VALUES (1, 'original weather')")
        conn.execute(MIGRATION.read_bytes())
        conn.execute(MIGRATION.read_bytes())
        assert conn.execute("SELECT * FROM daily_index").fetchall() == [(1, "original weather")]
        assert conn.execute("SELECT count(*) FROM browser_owners").fetchone() == (0,)


def test_fresh_seed_and_upgrade_preserve_weather_tables(database):
    """Execute fresh-install SQL and repeat the history migration with existing weather data."""
    seed = MIGRATION.parent.parent / "pgvector-seed.sql"
    fresh_sql = (
        seed.read_text()
        .replace("\\c vectorstore", "")
        .replace("\\ir migrations/001_conversations.sql", MIGRATION.read_text())
        .replace("\\ir migrations/002_turn_snapshots.sql", SNAPSHOT_MIGRATION.read_text())
    )
    with database() as conn:
        conn.execute(fresh_sql.encode())
        for table in ["daily_index", "live_index", "forecast_index"]:
            conn.execute(
                sql.SQL("INSERT INTO {} (id, document) VALUES (123, 'unchanged')").format(sql.Identifier(table))
            )
        conn.execute(MIGRATION.read_bytes())
        for table in ["daily_index", "live_index", "forecast_index"]:
            assert conn.execute(sql.SQL("SELECT id, document FROM {}").format(sql.Identifier(table))).fetchall() == [
                (123, "unchanged")
            ]


def test_migration_command_upgrades_existing_schema(database, monkeypatch, capsys):
    """The documented command locates and reapplies its SQL without touching weather records."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from scripts.migrate_conversations import main

    @contextmanager
    def connection():
        with database() as conn:
            yield SimpleNamespace(conn=conn)

    monkeypatch.setattr("scripts.migrate_conversations.PgVectorConnection", connection)
    monkeypatch.setattr("sys.argv", ["migrate_conversations"])
    main()
    main()
    assert "Weather indexes were not changed" in capsys.readouterr().out
