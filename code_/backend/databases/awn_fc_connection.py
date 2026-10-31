"""AgWeatherNet awn forecast database connection class."""

from datetime import datetime
from typing import override
from zoneinfo import ZoneInfo

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase


class AWNForecastDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "forecast"

    def __init__(self, **kwargs) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__(**kwargs)

    @override
    def format_table_name(self, station_id: int) -> str:
        year = datetime.now(ZoneInfo("America/Los_Angeles")).year
        return f"fcst_{int(station_id)}_{year}"


class AWNForecastFallbackDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "awnfc"

    def __init__(self, **kwargs) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__(**kwargs)

    @override
    def format_table_name(self, station_id: int) -> str:
        return f"forecast{station_id}"
