"""Tests for code.backend.databases.awn_connection."""

import dotenv
import pytest
from backend.databases.awn_connection import AWNDatabaseConnection


# Call loadenv function once this test file
@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


def test_awn_database_connection() -> None:
    """Check the credentials work, assumes your current ip can connect to the db host."""
    with AWNDatabaseConnection() as awn_db:
        assert awn_db.conn.is_connected(), "database connection failed."
