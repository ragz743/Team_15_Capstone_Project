"""AgWeatherNet awn database connection class."""

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase


class AWNDatabaseConnection(AWNDatabaseConnectionBase):
    """A database connector for the awn database."""

    _TABLE_NAME = "awn"

    def __init__(self) -> None:
        """Init an AWNDatabaseConnection."""
        super().__init__()
