"""AgWeatherNet awn forecast database connection class."""

from typing import override

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase


class AWNForecastDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "forecast"

    def __init__(self) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__()

    @override
    def format_table_name(self, station_id: int) -> str:
        return f"fcst_{station_id}_2026"


class AWNForecastFallbackDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "awnfc"

    def __init__(self) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__()

    @override
    def format_table_name(self, station_id: int) -> str:
        return f"forecast{station_id}"
