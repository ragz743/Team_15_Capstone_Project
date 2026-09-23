"""AgWeatherNet awn daily database connection class."""

from typing import override

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase


class AWNDailyDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "awndaily"

    def __init__(self) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__()

    @override
    def format_table_name(self, station_id: int) -> str:
        return f"station{station_id}daily"
