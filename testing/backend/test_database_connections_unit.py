"""Tests for AWN database connection classes."""

from __future__ import annotations

from typing import Any, cast

import pytest
from backend.databases import _awn_connection_base
from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_fc_connection import (
    AWNForecastDatabaseConnection,
    AWNForecastFallbackDatabaseConnection,
)
from backend.databases.awn_main_connection import AWNDatabaseConnection


class FakeMySQLConnection:
    """Minimal MySQL connection double."""

    def __init__(self, **kwargs: Any) -> None:
        """Capture connector arguments."""
        self.kwargs = kwargs
        self.disconnected = False
        self.cursors: list[FakeCursor] = []

    def disconnect(self) -> None:
        """Record disconnecting the connection."""
        self.disconnected = True

    def cursor(self) -> FakeCursor:
        """Return a fresh cursor double."""
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor


class FakeCursor:
    """Cursor double supporting iteration over query rows."""

    def __init__(self) -> None:
        """Initialize cursor query state."""
        self.query: str | None = None
        self.params: tuple[Any, ...] | None = None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        """Record query text and parameters."""
        self.query = query
        self.params = params

    def __iter__(self):
        """Return fixed schema result rows."""
        return iter([("COLUMN", "varchar", "YES", "", "description")])


def test_schema_query_result_parses_columns_and_rejects_short_rows() -> None:
    """Convert schema rows and reject malformed results."""
    result = _awn_connection_base.SchemaQueryResult.from_tuple(("name", "varchar", "YES", "", "comment"))
    assert result.column_name == "name"
    assert result.data_type == "varchar"
    assert result.column_comment == "comment"

    with pytest.raises(ValueError, match="unrecognized tuple structure"):
        _awn_connection_base.SchemaQueryResult.from_tuple(("name",))


@pytest.mark.parametrize(
    ("connection_type", "db_name", "table_name"),
    [
        (AWNDatabaseConnection, "awn", "station123"),
        (AWNDailyDatabaseConnection, "awndaily", "station123daily"),
        (AWNForecastDatabaseConnection, "forecast", "fcst_123_2026"),
        (AWNForecastFallbackDatabaseConnection, "awnfc", "forecast123"),
    ],
)
def test_awn_connection_configuration_and_table_names(
    monkeypatch: pytest.MonkeyPatch,
    connection_type: type,
    db_name: str,
    table_name: str,
) -> None:
    """Wire environment credentials, configured database, and station table names."""
    created: list[FakeMySQLConnection] = []

    def connect(**kwargs: Any) -> FakeMySQLConnection:
        connection = FakeMySQLConnection(**kwargs)
        created.append(connection)
        return connection

    monkeypatch.setattr(_awn_connection_base.connector, "MySQLConnection", connect)
    monkeypatch.setenv("AWN_DB_USER", "awn-user")
    monkeypatch.setenv("AWN_DB_PASSWORD", "awn-password")
    monkeypatch.setenv("AWN_DB_HOST", "awn.example")

    connection = connection_type()

    assert connection.conn.kwargs == {
        "user": "awn-user",
        "password": "awn-password",
        "host": "awn.example",
        "database": db_name,
    }
    assert connection.format_table_name(123) == table_name
    assert created == [connection.conn]


def test_awn_connection_query_schema_and_context_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetch schema metadata using parameterized queries and disconnect on exit."""
    instances: list[FakeMySQLConnection] = []

    def connect(**kwargs: Any) -> FakeMySQLConnection:
        connection = FakeMySQLConnection(**kwargs)
        instances.append(connection)
        return connection

    monkeypatch.setattr(_awn_connection_base.connector, "MySQLConnection", connect)
    connection = AWNDatabaseConnection()

    schema = connection.query_schema("station123")

    assert schema == [_awn_connection_base.SchemaQueryResult("COLUMN", "varchar", "YES", "", "description")]
    fake_connection = cast(FakeMySQLConnection, connection.conn)
    schema_query = fake_connection.cursors[0]
    assert schema_query.query is not None
    assert "INFORMATION_SCHEMA.COLUMNS" in schema_query.query
    assert schema_query.params == ("awn", "station123")
    assert fake_connection.kwargs["database"] == "awn"
    assert list(connection.simple_query("SELECT %s", (5,))) == [("COLUMN", "varchar", "YES", "", "description")]
    assert fake_connection.cursors[1].query == "SELECT %s"
    assert fake_connection.cursors[1].params == (5,)
    assert connection.query_schema("station123")[0].column_name == "COLUMN"
    with connection:
        assert connection.conn is instances[0]
    assert fake_connection.disconnected
