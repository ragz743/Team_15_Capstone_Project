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
        host: str = "localhost",
        port: int = 5432,
    ):
        """Create a pgvector database connection."""
        conn_info = {  # combine connection args into string using dictionary
            "host": host,
            "port": port,
            "user": os.getenv("PG_USER"),
            "password": os.getenv("PG_PASSWORD"),
            "dbname": self._DB_NAME,
        }
        self.conn = psycopg.connect(conninfo=" ".join({f"{k}={v}" for k, v in conn_info.items()}))

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
        cursor.execute(sql_query, query_vars)
        id = cursor.fetchone()
        self.conn.commit()

        return str(id)
