"""Offline unit tests for the pgvector connection wrapper."""

from __future__ import annotations

from typing import Any

from backend.databases import pgvector


class FakeCursor:
    """Cursor double that records executions and yields configured rows."""

    def __init__(self, rows: list[tuple[Any, ...]], inserted_row: tuple[Any, ...] | None = None) -> None:
        """Store query results and a row returned by fetchone."""
        self.rows = rows
        self.inserted_row = inserted_row
        self.executed: list[tuple[bytes, tuple[Any, ...]]] = []

    def execute(self, query: bytes, params: Any) -> None:
        """Record a statement and its parameters."""
        self.executed.append((query, tuple(params)))

    def __iter__(self):
        """Iterate the configured result rows."""
        return iter(self.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return the configured insert result."""
        return self.inserted_row


class FakeConnection:
    """Connection double for cursor, close, and transaction operations."""

    def __init__(self, cursor: FakeCursor) -> None:
        """Initialize connection state."""
        self._cursor = cursor
        self.closed = False
        self.commits = 0

    def cursor(self) -> FakeCursor:
        """Return the configured cursor."""
        return self._cursor

    def close(self) -> None:
        """Record closing the connection."""
        self.closed = True

    def commit(self) -> None:
        """Record committing the transaction."""
        self.commits += 1


def test_connection_uses_explicit_options_and_optional_credentials(monkeypatch) -> None:
    """Pass explicit host/port and configured credentials to psycopg."""
    connect_calls: list[dict[str, Any]] = []
    connection = FakeConnection(FakeCursor([]))
    monkeypatch.setattr(pgvector.psycopg, "connect", lambda **kwargs: connect_calls.append(kwargs) or connection)
    monkeypatch.setenv("PG_USER", "test-user")
    monkeypatch.setenv("PG_PASSWORD", "test-password")

    result = pgvector.PgVectorConnection(host="db.example", port=6432)

    assert result.conn is connection
    assert connect_calls == [
        {
            "host": "db.example",
            "port": 6432,
            "dbname": "vectorstore",
            "user": "test-user",
            "password": "test-password",
        }
    ]


def test_connection_uses_environment_host_and_port_without_credentials(monkeypatch) -> None:
    """Use environment endpoint settings and omit absent credentials."""
    connect_calls: list[dict[str, Any]] = []
    connection = FakeConnection(FakeCursor([]))
    monkeypatch.setattr(pgvector.psycopg, "connect", lambda **kwargs: connect_calls.append(kwargs) or connection)
    monkeypatch.setenv("PG_HOST", "postgres.internal")
    monkeypatch.setenv("PG_PORT", "6543")
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    pgvector.PgVectorConnection()

    assert connect_calls == [{"host": "postgres.internal", "port": 6543, "dbname": "vectorstore"}]


def test_connection_uses_local_defaults_when_endpoint_is_not_configured(monkeypatch) -> None:
    """Default to localhost and the standard PostgreSQL port."""
    connect_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pgvector.psycopg,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs) or FakeConnection(FakeCursor([])),
    )
    monkeypatch.delenv("PG_HOST", raising=False)
    monkeypatch.delenv("PG_PORT", raising=False)
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    pgvector.PgVectorConnection()

    assert connect_calls == [{"host": "localhost", "port": 5432, "dbname": "vectorstore"}]


def test_context_manager_returns_connection_wrapper_and_closes_connection(monkeypatch) -> None:
    """Return this wrapper from enter and close the underlying connection on exit."""
    connection = FakeConnection(FakeCursor([]))
    monkeypatch.setattr(pgvector.psycopg, "connect", lambda **kwargs: connection)
    wrapper = pgvector.PgVectorConnection()

    with wrapper as entered:
        assert entered is wrapper

    assert connection.closed


def test_simple_query_executes_and_yields_cursor_rows(monkeypatch) -> None:
    """Execute parameterized SQL and yield every returned row."""
    cursor = FakeCursor([("one",), ("two",)])
    connection = FakeConnection(cursor)
    monkeypatch.setattr(pgvector.psycopg, "connect", lambda **kwargs: connection)
    wrapper = pgvector.PgVectorConnection()

    assert list(wrapper.simple_query(b"SELECT value WHERE id = %s", (7,))) == [("one",), ("two",)]
    assert cursor.executed == [(b"SELECT value WHERE id = %s", (7,))]


def test_insert_commits_and_returns_stringified_row(monkeypatch) -> None:
    """Execute an insert, commit it, and return the fetched identifier."""
    cursor = FakeCursor([], inserted_row=(42,))
    connection = FakeConnection(cursor)
    monkeypatch.setattr(pgvector.psycopg, "connect", lambda **kwargs: connection)
    wrapper = pgvector.PgVectorConnection()

    assert wrapper.insert(b"INSERT INTO items VALUES (%s)", ("value",)) == "(42,)"
    assert cursor.executed == [(b"INSERT INTO items VALUES (%s)", ("value",))]
    assert connection.commits == 1
