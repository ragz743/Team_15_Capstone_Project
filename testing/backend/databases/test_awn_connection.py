"""Tests for code.backend.databases.awn_connection."""

import dotenv
import pytest
from backend.databases._awn_connection_base import AWNDatabaseConnectionBase
from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_fc_connection import AWNForecastDatabaseConnection
from backend.databases.awn_main_connection import AWNDatabaseConnection


# Call loadenv function once this test file
@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


@pytest.mark.parametrize(
    "db_class",
    [
        AWNDatabaseConnection,
        AWNDailyDatabaseConnection,
        AWNForecastDatabaseConnection,
    ],
)
def test_awn_database_connection(
    db_class: type[AWNDatabaseConnectionBase],
) -> None:
    """Check the credentials work, assumes your current ip can connect to the db host."""
    with db_class() as awn_db:
        assert awn_db.conn.is_connected(), "database connection failed."
