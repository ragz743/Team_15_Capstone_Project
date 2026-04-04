"""AgWeatherNet MySQL database connection class."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Self

from mysql import connector


class AWNDatabaseConnection:
    """Connect to the AgWeatherNet MySQL database."""

    def __init__(self) -> None:
        """Create a new AWN Database Connection."""
        self.conn: connector.MySQLConnection = connector.MySQLConnection(
            user=os.getenv("AWN_DB_USER"),
            password=os.getenv("AWN_DB_PASSWORD"),
            host=os.getenv("AWN_DB_HOST"),
            # database="awn",
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
