"""Tests for code.backend.databases.awn_connection."""

import dotenv
import pytest
from backend.databases import pgvector


# Call loadenv function once this test file
@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


def test_awn_database_connection() -> None:
    """Check the credentials work, assumes your current ip can connect to the db host."""
    with pgvector.PgVectorConnection() as vectorstore:
        assert vectorstore.conn.execute("SELECT 1"), "database connection failed."
