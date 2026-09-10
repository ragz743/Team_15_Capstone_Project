"""Tests for code.backend.databases.awn_connection."""

import dotenv
import pytest
from backend.databases._awn_connection_base import AWNDatabaseConnectionBase
from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_fc_connection import AWNForecastDatabaseConnection
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.loaders import _common


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
def test_awn_database_connection(db_class: type[AWNDatabaseConnectionBase]) -> None:
    """Check the credentials work, assumes your current ip can connect to the db host."""
    with db_class() as awn_db:
        assert awn_db.conn.is_connected(), "database connection failed."


@pytest.mark.parametrize(
    ("db_class", "table_name"),
    [
        (AWNDatabaseConnection, "METADATA"),
        # (AWNDatabaseConnection, "station042"),
        # (AWNDailyDatabaseConnection, "station100004daily"),
        # (AWNForecastDatabaseConnection, "fcst_100000_2026"),
    ],
)
def test_awn_table_info_query(db_class: type[AWNDatabaseConnectionBase], table_name: str) -> None:
    """Query the table information for each database."""
    with db_class() as awn_db:
        schema = awn_db.query_schema(table_name)
        print(_common.to_markdown_table(schema, ["", "", "", "", ""]))
