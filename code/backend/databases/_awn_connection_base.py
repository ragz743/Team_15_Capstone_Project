"""AgWeatherNet MySQL database connection class."""

from __future__ import annotations

import os
from abc import ABC
from types import TracebackType
from typing import Any, ClassVar, Generator, NamedTuple, Self, Sequence

from mysql import connector


class SchemaQueryResult(NamedTuple):
    """The fields returned from a schema query."""

    column_name: str
    data_type: str
    is_nullable: str
    column_key: str
    column_comment: str

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a SchemaQueryResult from a tuple."""
        match row[:5]:
            case (name, type_, nullable, key, comment):
                return cls(
                    name,
                    type_,
                    nullable,
                    key,
                    comment,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)


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

    def query_schema(self, table_name: str) -> list[SchemaQueryResult]:
        """Query table schema given a table name."""
        cols = ", ".join(map(lambda s: s.upper(), SchemaQueryResult._fields))
        # column list is built from fixed field names, not user input, so inlining it is safe
        query_schema = f"""
        SELECT {cols}
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s
        AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """
        results = self.simple_query(query_schema, (self._DB_NAME, table_name))
        return [SchemaQueryResult.from_tuple(tup) for tup in results]
