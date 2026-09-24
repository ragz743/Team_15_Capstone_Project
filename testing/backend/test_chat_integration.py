"""Exercise the HTTP chat contract using controlled weather records and model responses."""

from datetime import date
from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from backend.weather_query import Station, WeatherQuery
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pytest import MonkeyPatch

STATIONS = [Station("100093", "Pullman", "Whitman")]
SELECTION = WeatherQuery(("100093",), date(2026, 9, 9), date(2026, 9, 9))


def test_chat_passes_retrieved_weather_to_model_and_returns_reply(monkeypatch: MonkeyPatch) -> None:
    """Exercise API and real retriever together without external services."""
    store = MagicMock(spec=PgVectorStore)
    store.stations.return_value = STATIONS
    store.similarity_search.return_value = [Document(page_content="Pullman, 2026-09-09: temperature 72°F.")]
    chatbot = MagicMock()
    chatbot.invoke.return_value = "Pullman's temperature on September 9 was 72°F."
    monkeypatch.setattr(api, "_retriever", Retriever(store, chatbot))
    monkeypatch.setattr(api, "_chatbot_model_name", "test-model")

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "  Temperature in Pullman on 2026-09-09?  "}]}
    )

    assert response.status_code == 200
    assert response.json() == {"reply": chatbot.invoke.return_value, "model": "test-model"}
    store.similarity_search.assert_called_once_with(
        "Temperature in Pullman on 2026-09-09?", k=8, filter=None, selection=SELECTION
    )
    prompt = chatbot.invoke.call_args.args[0][0]
    assert "Pullman, 2026-09-09: temperature 72°F." in prompt
    assert "Temperature in Pullman on 2026-09-09?" in prompt


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
        store.stations.return_value = STATIONS
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
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman on 2026-09-09?"}]}
    )
    assert response.status_code == 200
    assert response.json() == {"reply": model.invoke.return_value, "model": "test-model"}
    for index in indexes:
        index.similarity_search.assert_called_once_with(
            "Temperature at Pullman on 2026-09-09?", k=8, filter=None, selection=SELECTION
        )
    model.invoke.assert_called_once()
    assert "Station: Pullman" in model.invoke.call_args.args[0][0]


def test_all_empty_stores_skip_the_answer_model(monkeypatch):
    """No-data requires successful empty searches from all three indexes."""
    indexes, model = stores(), MagicMock()
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, model))
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman on 2026-09-09?"}]}
    )
    assert response.status_code == 200
    assert "No matching weather records" in response.json()["reply"]
    assert all(index.similarity_search.call_count == 1 for index in indexes)
    model.invoke.assert_not_called()


@pytest.mark.parametrize("operation", ["stations", "similarity_search"])
def test_database_failure_is_not_no_data(monkeypatch, operation):
    """Failed catalog or weather queries remain service errors."""
    indexes, model = stores(), MagicMock()
    getattr(indexes[1], operation).side_effect = RuntimeError("private connection details")
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, model))
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Temperature at Pullman on 2026-09-09?"}]}
    )
    assert response.status_code == 502
    assert "private connection details" not in response.text
    assert "No matching weather records" not in response.text
    model.invoke.assert_not_called()


@pytest.mark.parametrize("metadata_filter", [{"id": "100093"}, {"station": "Pullman"}, {"county": "Whitman"}])
def test_api_filter_reaches_every_store(monkeypatch, metadata_filter):
    """The HTTP metadata filter reaches all three searches."""
    indexes = stores()
    monkeypatch.setattr(api, "_retriever", Retriever(indexes, MagicMock()))
    response = TestClient(api.app).post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Temperature on 2026-09-09?"}], "filter": metadata_filter},
    )
    assert response.status_code == 200
    selection = WeatherQuery(SELECTION.station_ids, SELECTION.start, SELECTION.end, metadata_filter.get("county"))
    for index in indexes:
        index.similarity_search.assert_called_once_with(
            "Temperature on 2026-09-09?", k=8, filter=metadata_filter, selection=selection
        )
        index.stations.assert_called_once_with()


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


def test_location_and_date_reach_sql_and_answer_context(monkeypatch: MonkeyPatch) -> None:
    """Preserve each record's identity through the user-facing endpoint."""
    connection, embedding = MagicMock(), MagicMock()
    embedding.embed_document.return_value = ([0.0, 0.0, 0.0], Document(page_content="query"))
    monkeypatch.setattr("backend.vector_store.PgVectorConnection", lambda: connection)
    store = PgVectorStore(embedding)
    connection.simple_query.side_effect = [
        [("1", "Pullman", "Whitman"), ("2", "Colfax", "Whitman")],
        [
            (
                "temperature 72°F",
                {
                    "id": "1",
                    "station": "Pullman",
                    "county": "Whitman",
                    "date": "2026-09-09",
                    "latitude": "private coordinate",
                },
            ),
            ("temperature 60°F", {"id": "2", "station": "Colfax", "county": "Whitman", "date": "2026-09-09"}),
        ],
    ]
    chatbot = MagicMock()
    chatbot.invoke.return_value = "At Pullman on 2026-09-09, temperature was 72°F."
    monkeypatch.setattr(api, "_retriever", Retriever(store, chatbot))
    monkeypatch.setattr(api, "_chatbot_model_name", "fixture")
    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Whitman County on 2026-09-09"}]}
    )
    assert response.status_code == 200
    assert response.json()["reply"].startswith(chatbot.invoke.return_value)
    query, params = connection.simple_query.call_args.args
    assert params[:3] == (["1", "2"], "2026-09-09", "2026-09-09")
    assert b"ANY(%s)" in query
    prompt = chatbot.invoke.call_args.args[0][0]
    for value in ("Station: Pullman", "Station ID: 1", "Station: Colfax", "Observation date: 2026-09-09"):
        assert value in prompt
    assert "private coordinate" not in prompt
