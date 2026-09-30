"""Serve the built UI with controlled models and disposable PostgreSQL history."""

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import backend.api as api
import dotenv
import uvicorn
from backend.conversation_store import ConversationStore
from backend.databases.pgvector import PgVectorConnection
from backend.history_service import HistoryService
from backend.weather_query import Station
from backend.workflow.engine import LangGraphEngine
from fastapi.staticfiles import StaticFiles
from history_fixture import FixtureHistoryModel
from psycopg import sql
from pytest import MonkeyPatch
from workflow_fixture import make_graph

ROOT = Path(__file__).resolve().parents[1]


def weather_engine(patch):
    """Run the real graph with a controlled station catalog and source records."""
    runtime = make_graph(patch)
    directory = MagicMock()
    directory.stations.return_value = [
        Station("1", "Central source", "Kittitas", "47.201", "120.501", "WA"),
        Station("2", "Eastern source", "Grant", "47.201", "120.001", "WA"),
    ]
    plan = runtime.classifier.invoke_json.return_value
    attempts = {}

    def classify(instructions, payload, schema):
        question = payload["question"]
        attempts[question] = attempts.get(question, 0) + 1
        if question == "Retry weather" and attempts[question] == 1:
            raise RuntimeError("Controlled provider failure")
        return plan

    def answer(messages):
        return (
            "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily"
            if "SQL" in messages[0] and "Answer the user's original" not in messages[0]
            else "The nearby source reported 70.25 F on September 29, 2026."
        )

    runtime.classifier.invoke_json.side_effect = classify
    runtime.model.invoke.side_effect = answer
    return LangGraphEngine(runtime.model, runtime.classifier, directory=directory)


@asynccontextmanager
async def fixture_lifespan(app):
    """Create and remove only a unique test schema for this browser run."""
    schema = "test_pr90_browser_" + uuid4().hex

    def connect():
        conn = PgVectorConnection(host="127.0.0.1", port=5432, connect_timeout=5).conn
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.commit()
        return conn

    with connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for migration in sorted((ROOT / "deployment/migrations").glob("*.sql")):
            conn.execute(migration.read_bytes())
    patch = MonkeyPatch()
    try:
        api._conversations = ConversationStore(connect)
        api._history_service = HistoryService(FixtureHistoryModel(), "fixture-history")
        api._retriever = weather_engine(patch)
        api._chatbot_model_name = "fixture-weather"
        yield
    finally:
        patch.undo()
        with connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def main():
    """Run only on loopback with optional local environment configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int, default=8890)
    args = parser.parse_args()
    dotenv.load_dotenv(args.env_file)
    os.environ["AWN_COOKIE_SECURE"] = "false"
    api.app.router.lifespan_context = fixture_lifespan
    api.app.mount("/", StaticFiles(directory=ROOT / "code_/frontend/dist", html=True))
    uvicorn.run(api.app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
