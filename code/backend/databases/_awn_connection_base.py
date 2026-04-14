"""AgWeatherNet MySQL database connection class."""

from __future__ import annotations

import os
from abc import ABC
from types import TracebackType
from typing import Any, ClassVar, Generator, Self, Sequence

from mysql import connector


class AWNDatabaseConnectionBase(ABC):
    """AgWeatherNet MySQL database connection base class."""

    _DB_NAME: ClassVar[str]

    def __init__(self) -> None:
        """Create a new AWN Database Connection."""
        self.conn: connector.MySQLConnection = connector.MySQLConnection(
            user=os.getenv("AWN_DB_USER"),
            password=os.getenv("AWN_DB_PASSWORD"),
            host=os.getenv("AWN_DB_HOST"),
            database=self._DB_NAME,
        )

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
        self.conn.disconnect()

    def simple_query(self, sql_query: str, query_vars: Sequence[Any]) -> Generator[Sequence[Any]]:
        """Make a simple query to the connected database."""
        cursor = self.conn.cursor()

        # make the query
        cursor.execute(sql_query, query_vars)

        # iter through result tuples, can be any number of rows so be careful!
        for query_fields in cursor:
            yield query_fields
