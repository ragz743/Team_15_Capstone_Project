"""Prepare conversation tables and search indexes before the API accepts requests."""

import argparse
from pathlib import Path

import dotenv
from backend.databases.pgvector import PgVectorConnection

# Only repeatable migrations belong in the API startup path. The station
# directory migration is a one-time backfill applied separately on upgrades.
STARTUP_MIGRATIONS = (
    "001_conversations.sql",
    "001_station_search_indexes.sql",
    "002_turn_snapshots.sql",
    "003_search_indexes.sql",
)


def main() -> None:
    """Upgrade an existing database using the same SQL as fresh installations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sql",
        type=Path,
        help="Apply one explicit SQL file instead of all bundled conversation migrations.",
    )
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[2] / "deployment/migrations"
    migrations = [args.sql] if args.sql is not None else [directory / name for name in STARTUP_MIGRATIONS]
    if not all(migration.is_file() for migration in migrations):
        parser.error("One or more conversation migrations were not found")
    dotenv.load_dotenv()
    with PgVectorConnection() as database:
        with database.conn.transaction(), database.conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT pg_advisory_xact_lock(719034201)")
            for migration in migrations:
                cur.execute(migration.read_bytes())
    print("Conversation schema and search indexes are ready. Existing records were preserved.")


if __name__ == "__main__":
    main()
