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
from backend.models._chatbot_base import _BaseChatbot
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from backend.weather_query import Station
from fastapi.staticfiles import StaticFiles
from history_fixture import FixtureHistoryModel
from langchain_core.documents import Document
from psycopg import sql
from weather_fixtures import intent_json

ROOT = Path(__file__).resolve().parents[1]


class WeatherModel(_BaseChatbot):
    """Provide controlled outputs for browser wiring checks only."""

    def invoke_json(self, instructions, payload, schema):
        """Preserve the submitted question in a fixed valid interpretation."""
        return intent_json(question=payload["question"], data_kind="observation")

    def invoke(self, messages):
        """Return one synthetic measurement for UI assertions."""
        return "The nearby source reported 72 F on September 9, 2026."


def weather_store():
    """Supply indexed sources without using application weather data."""
    store = MagicMock(spec=PgVectorStore)
    store.table = "daily_index"
    store.stations.return_value = [
        Station("1", "Central source", "Kittitas", "47.201", "120.501", "WA"),
        Station("2", "Eastern source", "Grant", "47.201", "120.001", "WA"),
    ]
    attempts = {}

    def search(question, *, selection, **kwargs):
        attempts[question] = attempts.get(question, 0) + 1
        if question == "Retry weather" and attempts[question] == 1:
            raise RuntimeError("Controlled retrieval failure")
        station = next(station for station in store.stations.return_value if station.id == selection.station_ids[0])
        return [
            Document(
                page_content="Temperature 72 F",
                metadata={
                    "id": station.id,
                    "station": station.name,
                    "county": station.county,
                    "date": "2026-09-09",
                },
            )
        ]

    store.similarity_search.side_effect = search
    return store


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
    try:
        api._conversations = ConversationStore(connect)
        api._history_service = HistoryService(FixtureHistoryModel(), "fixture-history")
        api._retriever = Retriever(weather_store(), WeatherModel())
        api._chatbot_model_name = "fixture-weather"
        yield
    finally:
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
