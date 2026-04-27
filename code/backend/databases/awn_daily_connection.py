"""AgWeatherNet awn daily database connection class."""

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase


class AWNDailyDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _DB_NAME = "awndaily"

    def __init__(self) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__()
