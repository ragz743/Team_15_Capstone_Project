"""Apply the conversation migration without changing weather tables."""

import argparse
from pathlib import Path

import dotenv
from backend.databases.pgvector import PgVectorConnection


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
    migrations = [args.sql] if args.sql is not None else sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        parser.error("No conversation migrations were found")
    dotenv.load_dotenv()
    with PgVectorConnection() as database:
        with database.conn.transaction(), database.conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            for migration in migrations:
                cur.execute(migration.read_bytes())
    print("Conversation schema is ready. Weather indexes were not changed.")


if __name__ == "__main__":
    main()
