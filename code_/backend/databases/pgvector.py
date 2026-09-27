"""Postgres pgvector database connection class."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any, Generator, Self, Sequence

import psycopg


class PgVectorConnection:
    """The pgvector database connection."""

    _DB_NAME: str = "vectorstore"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ):
        """Create a pgvector database connection."""
        host = host if host is not None else os.getenv("PG_HOST", "localhost")
        port = port if port is not None else int(os.getenv("PG_PORT", "5432"))

        conn_info: dict[str, Any] = {
            "host": host,
            "port": port,
            "dbname": self._DB_NAME,
        }

        user = os.getenv("PG_USER")
        password = os.getenv("PG_PASSWORD")
        if user is not None:
            conn_info["user"] = user
        if password is not None:
            conn_info["password"] = password

        self.conn = psycopg.connect(**conn_info)

    def __enter__(self) -> Self:
        """Open the database connection using a context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        """Close the database connection by exiting with context manager."""
        self.conn.close()

    def simple_query(self, sql_query: bytes, query_vars: Sequence[Any]) -> Generator[Sequence[Any]]:
        """Make a simple query to the connected database."""
        cursor = self.conn.cursor()

        # make the query
        cursor.execute(sql_query, query_vars)

        # iter through result tuples, can be any number of rows so be careful!
        for query_fields in cursor:
            yield query_fields

    def insert(self, sql_query: bytes, query_vars: Sequence[Any]) -> str:
        """Insert data into the database sing the sql_query and parameters."""
        cursor = self.conn.cursor()

        # execute the query and save changes before exit
        id = cursor.execute(sql_query, query_vars).fetchone()
        self.conn.commit()

        return str(id)
