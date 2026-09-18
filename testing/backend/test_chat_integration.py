"""Exercise the HTTP chat contract using controlled weather records and model responses."""

import json
import os
from unittest.mock import MagicMock

import backend.api as api
import backend.vector_store as vector_store
import pytest
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from psycopg import sql
from pytest import MonkeyPatch


def test_chat_passes_retrieved_weather_to_model_and_returns_reply(monkeypatch: MonkeyPatch) -> None:
    """Exercise API and real retriever together without external services."""
    store = MagicMock()
    store.similarity_search.return_value = [Document(page_content="Pullman, 2026-09-09: temperature 72°F.")]
    chatbot = MagicMock()
    chatbot.invoke.return_value = "Pullman's temperature on September 9 was 72°F."
    monkeypatch.setattr(api, "_retriever", Retriever(store, chatbot))
    monkeypatch.setattr(api, "_chatbot_model_name", "test-model")

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "  Temperature in Pullman?  "}]}
    )

    assert response.status_code == 200
    assert response.json() == {"reply": chatbot.invoke.return_value, "model": "test-model"}
    store.similarity_search.assert_called_once_with("Temperature in Pullman?", k=8, filter=None)
    prompt = chatbot.invoke.call_args.args[0][0]
    assert "Pullman, 2026-09-09: temperature 72°F." in prompt
    assert "Temperature in Pullman?" in prompt


@pytest.mark.parametrize("content", ["", " ", "\n\t"])
def test_chat_rejects_blank_input_without_retrieval(monkeypatch: MonkeyPatch, content: str) -> None:
    """Reject empty and whitespace-only questions before any service calls."""
    retriever = MagicMock()
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post("/api/chat", json={"messages": [{"role": "user", "content": content}]})
    assert response.status_code in (400, 422)
    retriever.retrieve.assert_not_called()


def test_chat_reports_unavailable_backend(monkeypatch: MonkeyPatch) -> None:
    """An uninitialized service produces an actionable response for the UI."""
    monkeypatch.setattr(api, "_retriever", None)
    response = TestClient(api.app).post("/api/chat", json={"messages": [{"role": "user", "content": "Weather?"}]})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_chat_reports_retrieval_failure_without_internal_details(monkeypatch: MonkeyPatch) -> None:
    """Keep connection and provider diagnostics in server logs."""
    retriever = MagicMock()
    retriever.retrieve.side_effect = RuntimeError("private database connection details")
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post("/api/chat", json={"messages": [{"role": "user", "content": "Weather?"}]})
    assert response.status_code == 502
    assert "Please try again" in response.json()["detail"]
    assert "private database" not in response.text


@pytest.mark.parametrize("reply", ["", " \n"])
def test_chat_rejects_empty_model_reply(monkeypatch: MonkeyPatch, reply: str) -> None:
    """Do not present a blank assistant bubble as a successful answer."""
    retriever = MagicMock()
    retriever.retrieve.return_value = reply
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post("/api/chat", json={"messages": [{"role": "user", "content": "Weather?"}]})
    assert response.status_code == 502
    assert "empty answer" in response.json()["detail"]


def stores():
    """Create empty stores with the same interfaces as the database stores."""
    result = []
    for table in ("daily_index", "live_index", "forecast_index"):
        store = MagicMock(spec=PgVectorStore)
        store.table = table
        store.distinct_metadata_values.return_value = []
        store.similarity_search.return_value = []
        result.append(store)
    return result


@pytest.mark.parametrize("matching_store", [0, 1, 2])
def test_answer_uses_records_from_any_store(monkeypatch, matching_store):
    """An empty index does not hide a match from another index."""
    indexes = stores()
    indexes[matching_store].similarity_search.return_value = [
        Document(page_content="Station: Pullman\nTemperature: 72 F")
    ]
    model = MagicMock()
    model.invoke.return_value = "At Pullman the temperature was 72 F."
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, model))
    monkeypatch.setattr(api, "_chatbot_model_name", "test-model")
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman?"}]}
    )
    assert response.status_code == 200
    assert response.json() == {"reply": model.invoke.return_value, "model": "test-model"}
    for index in indexes:
        index.similarity_search.assert_called_once_with("Temperature at Pullman?", k=8, filter=None)
    model.invoke.assert_called_once()
    assert "Station: Pullman" in model.invoke.call_args.args[0][0]


def test_all_empty_stores_skip_the_answer_model(monkeypatch):
    """No-data requires successful empty searches from all three indexes."""
    indexes, model = stores(), MagicMock()
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, model))
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman?"}]}
    )
    assert response.status_code == 200
    assert "No matching weather records" in response.json()["reply"]
    assert all(index.similarity_search.call_count == 1 for index in indexes)
    model.invoke.assert_not_called()


@pytest.mark.parametrize("operation", ["distinct_metadata_values", "similarity_search"])
def test_database_failure_is_not_no_data(monkeypatch, operation):
    """Failed catalog or weather queries remain service errors."""
    indexes, model = stores(), MagicMock()
    getattr(indexes[1], operation).side_effect = RuntimeError("private connection details")
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, model))
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman?"}]}
    )
    assert response.status_code == 502
    assert "private connection details" not in response.text
    assert "No matching weather records" not in response.text
    model.invoke.assert_not_called()


def test_api_filter_reaches_every_store(monkeypatch):
    """The HTTP metadata filter reaches all three searches."""
    indexes = stores()
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, MagicMock()))
    response = TestClient(api.app).post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Temperature?"}], "filter": {"id": "100093"}},
    )
    assert response.status_code == 200
    for index in indexes:
        index.similarity_search.assert_called_once_with("Temperature?", k=8, filter={"id": "100093"})
        index.distinct_metadata_values.assert_not_called()


def test_startup_configures_all_indexes(monkeypatch):
    """The API applies the intended live and forecast staleness cutoffs."""
    embedding, model, store_class = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setattr(api, "EmbeddingOpenRouter", lambda _: embedding)
    monkeypatch.setattr(api, "ChatbotOpenRouter", lambda _: model)
    monkeypatch.setattr(api, "PgVectorStore", store_class)
    api._build_retriever()
    assert [call.kwargs for call in store_class.call_args_list] == [
        {"table": "daily_index"},
        {"table": "live_index", "staleness_days": 30},
        {"table": "forecast_index", "staleness_days": 2},
    ]


@pytest.mark.skipif(os.getenv("RUN_PGVECTOR_TESTS") != "1", reason="Requires local PostgreSQL")
@pytest.mark.parametrize("table", ["daily_index", "live_index", "forecast_index"])
def test_sql_filters_before_ranking(monkeypatch, table):
    """Temporary tables verify metadata and freshness filtering before LIMIT."""
    from backend.databases.pgvector import PgVectorConnection

    connection = PgVectorConnection(host="127.0.0.1", port=5432)
    try:
        connection.conn.execute(
            sql.SQL("CREATE TEMP TABLE {} (document text, metadata jsonb, embedding vector(3))").format(
                sql.Identifier(table)
            )
        )
        row = connection.conn.execute("SELECT CURRENT_DATE").fetchone()
        assert row is not None
        today = row[0].isoformat()
        for station, stamp, vector in [
            ("Other", today, "[0,0,0]"),
            ("Pullman", "2000-01-01", "[0,0,0]"),
            ("Pullman", today, "[1,1,1]"),
        ]:
            connection.conn.execute(
                sql.SQL("INSERT INTO {} VALUES (%s,%s,%s)").format(sql.Identifier(table)),
                (station, json.dumps({"station": station, "date": stamp, "timestamp": stamp}), vector),
            )
        monkeypatch.setattr(vector_store, "PgVectorConnection", lambda: connection)
        embedding = MagicMock()
        embedding.embed_document.return_value = ([0, 0, 0], Document(page_content="query"))
        store = PgVectorStore(embedding, table=table, staleness_days=2)
        result = store.similarity_search("Temperature?", k=1, filter={"station": "Pullman"})
        assert len(result) == 1
        assert result[0].metadata == {"station": "Pullman", "date": today, "timestamp": today}
    finally:
        connection.conn.rollback()
        connection.conn.close()
