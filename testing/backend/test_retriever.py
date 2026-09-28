"""Tests for backend.retriever and the retrieve CLI script."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from backend.retriever import RAG_PROMPT_TEMPLATE, Retriever
from backend.vector_store import PgVectorStore
from backend.weather_query import RequestedPoint, Station, WeatherQuery
from langchain_core.documents import Document

POINT = RequestedPoint(latitude=46.73, longitude=-117.18)
STATIONS = [Station("100093", "Pullman", "Whitman", "46.731", "117.181", "WA")]
SELECTION = WeatherQuery(("100093",), date(2026, 9, 9), date(2026, 9, 9))


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    store = MagicMock(spec=PgVectorStore)
    store.table = "daily_index"
    store.stations.return_value = STATIONS
    store.similarity_search.return_value = [
        Document(
            page_content="Temperature: 72F",
            metadata={"id": "100093", "station": "Pullman", "county": "Whitman", "date": "2026-09-09"},
        ),
        Document(
            page_content="Humidity: 45%",
            metadata={"id": "100093", "station": "Pullman", "county": "Whitman", "date": "2026-09-09"},
        ),
    ]
    return store


@pytest.fixture
def mock_chatbot():
    """Create a mock chatbot."""
    chatbot = MagicMock()
    chatbot.invoke.return_value = "The temperature at Pullman is 72F."
    return chatbot


def test_rag_prompt_template_has_required_variables():
    """Check that the prompt template contains context and question variables."""
    assert "context" in RAG_PROMPT_TEMPLATE.input_variables
    assert "question" in RAG_PROMPT_TEMPLATE.input_variables


def test_retriever_calls_vector_store(mock_vector_store, mock_chatbot):
    """Check that retrieve calls each vector store with the question."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the temperature at Pullman on 2026-09-09?", point=POINT)
    mock_vector_store.similarity_search.assert_called_once_with(
        "What is the temperature at Pullman on 2026-09-09?", k=8, selection=SELECTION
    )


def test_retriever_calls_chatbot(mock_vector_store, mock_chatbot):
    """Check that retrieve passes a formatted prompt to the chatbot."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the temperature at Pullman on 2026-09-09?", point=POINT)
    mock_chatbot.invoke.assert_called_once()


def test_retriever_returns_chatbot_response(mock_vector_store, mock_chatbot):
    """Append one source label for duplicate records from the same station and day."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    response = retriever.retrieve("What is the temperature at Pullman on 2026-09-09?", point=POINT)
    assert response == (
        "The temperature at Pullman is 72F.\n\nRetrieved records:\n"
        "Pullman (station 100093), Whitman County: 2026-09-09 (observation)\n"
        "These records may not cover every station or day you requested."
    )


def test_retriever_queries_all_stores(mock_chatbot):
    """Check that retrieve calls similarity_search on every store in the list."""
    store_a = MagicMock()
    store_a.stations.return_value = STATIONS
    store_a.similarity_search.return_value = [
        Document(page_content="Rain: 0.2 in", metadata={"id": "100093", "station": "Pullman", "date": "2026-09-09"})
    ]
    store_a.table = "daily_index"
    store_b = MagicMock()
    store_b.stations.return_value = STATIONS
    store_b.similarity_search.return_value = [
        Document(
            page_content="Wind: 12 mph",
            metadata={"id": "100093", "station": "Pullman", "timestamp": "2026-09-09 12:00:00"},
        )
    ]
    store_b.table = "live_index"

    retriever = Retriever([store_a, store_b], mock_chatbot)
    retriever.retrieve("What is the wind speed at Pullman on 2026-09-09?", point=POINT)

    store_a.similarity_search.assert_called_once_with(
        "What is the wind speed at Pullman on 2026-09-09?", k=8, selection=SELECTION
    )
    store_b.similarity_search.assert_called_once_with(
        "What is the wind speed at Pullman on 2026-09-09?", k=8, selection=SELECTION
    )


def test_retriever_handles_empty_store_results(mock_chatbot):
    """Empty retrieval returns an explanation without calling the chatbot."""
    store = MagicMock()
    store.stations.return_value = STATIONS
    store.similarity_search.return_value = []
    store.table = "live_index"

    retriever = Retriever([store], mock_chatbot)
    response = retriever.retrieve("What is the humidity at Pullman on 2026-09-09?", point=POINT)

    assert "No matching weather records" in response
    mock_chatbot.invoke.assert_not_called()


def test_retriever_context_includes_section_label(mock_chatbot):
    """Check that the prompt sent to the chatbot contains a labeled section header."""
    store = MagicMock()
    store.stations.return_value = STATIONS
    store.similarity_search.return_value = [
        Document(page_content="Temp: 65F", metadata={"id": "100093", "station": "Pullman", "date": "2026-09-09"})
    ]
    store.table = "daily_index"

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("Historical temperature at Pullman on 2026-09-09?", point=POINT)

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "[Historical Data]" in prompt_arg


def test_retriever_accepts_single_store(mock_chatbot):
    """Check that Retriever wraps a bare PgVectorStore in a list."""
    from backend.vector_store import PgVectorStore

    store = MagicMock(spec=PgVectorStore)
    store.stations.return_value = STATIONS
    store.similarity_search.return_value = []
    store.table = "forecast_index"

    retriever = Retriever(store, mock_chatbot)
    retriever.retrieve("Will it rain at Pullman on 2026-09-09?", point=POINT)

    store.similarity_search.assert_called_once_with("Will it rain at Pullman on 2026-09-09?", k=8, selection=SELECTION)


def test_retriever_prompt_contains_question(mock_vector_store, mock_chatbot):
    """Check that the formatted prompt contains the user's question."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the forecast for Pullman on 2026-09-09?", point=POINT)

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "What is the forecast for Pullman on 2026-09-09?" in prompt_arg


def test_retriever_prompt_contains_context(mock_vector_store, mock_chatbot):
    """Check that the formatted prompt includes document content from the store."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the humidity at Pullman on 2026-09-09?", point=POINT)

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "Humidity: 45%" in prompt_arg


@pytest.mark.parametrize(
    ("question", "message"),
    [
        ("Weather at Pullman on 2026-02-30", "invalid"),
        ("Weather at Pullman", "date"),
    ],
)
def test_unresolved_question_skips_search_and_model(mock_vector_store, mock_chatbot, question, message):
    """Ask for clarification before embeddings or answer generation."""
    reply = Retriever(mock_vector_store, mock_chatbot).retrieve(question, point=POINT)
    assert message in reply
    mock_vector_store.similarity_search.assert_not_called()
    mock_chatbot.invoke.assert_not_called()


def test_empty_catalog_skips_search_and_model(mock_vector_store, mock_chatbot):
    """An empty catalog cannot support a weather answer."""
    mock_vector_store.stations.return_value = []
    reply = Retriever(mock_vector_store, mock_chatbot).retrieve("Pullman on 2026-09-09", point=POINT)
    assert "No indexed weather source" in reply
    mock_vector_store.similarity_search.assert_not_called()
    mock_chatbot.invoke.assert_not_called()


def test_empty_retrieval_returns_no_data_without_calling_chatbot(
    mock_vector_store: MagicMock, mock_chatbot: MagicMock
) -> None:
    """Do not generate a weather answer without supporting records."""
    mock_vector_store.similarity_search.return_value = []

    response = Retriever(mock_vector_store, mock_chatbot).retrieve(
        "What is the temperature at Pullman on 2026-09-09?", point=POINT
    )

    assert "No matching weather records" in response
    assert "cannot provide an answer" in response
    mock_chatbot.invoke.assert_not_called()


def test_retrieval_failure_is_not_reported_as_missing_data(
    mock_vector_store: MagicMock, mock_chatbot: MagicMock
) -> None:
    """Keep infrastructure errors distinct from successful searches with no results."""
    mock_vector_store.similarity_search.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        Retriever(mock_vector_store, mock_chatbot).retrieve(
            "What is the temperature at Pullman on 2026-09-09?", point=POINT
        )

    mock_chatbot.invoke.assert_not_called()
