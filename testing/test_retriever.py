"""Tests for backend.retriever."""

from unittest.mock import MagicMock

import pytest
from backend.retriever import RAG_PROMPT_TEMPLATE, Retriever
from langchain_core.documents import Document


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    store = MagicMock()
    store.similarity_search.return_value = [
        Document(page_content="Temperature: 72F", metadata={"station": "Pullman"}),
        Document(page_content="Humidity: 45%", metadata={"station": "Pullman"}),
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
    retriever.retrieve("What is the temperature?")
    mock_vector_store.similarity_search.assert_called_once_with("What is the temperature?", filter=None)


def test_retriever_calls_chatbot(mock_vector_store, mock_chatbot):
    """Check that retrieve passes a formatted prompt to the chatbot."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the temperature?")
    mock_chatbot.invoke.assert_called_once()


def test_retriever_returns_chatbot_response(mock_vector_store, mock_chatbot):
    """Check that retrieve returns the chatbot response."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    response = retriever.retrieve("What is the temperature?")
    assert response == "The temperature at Pullman is 72F."


def test_retriever_queries_all_stores(mock_chatbot):
    """Check that retrieve calls similarity_search on every store in the list."""
    store_a = MagicMock()
    store_a.similarity_search.return_value = [Document(page_content="Rain: 0.2 in", metadata={})]
    store_a.table = "daily_index"
    store_b = MagicMock()
    store_b.similarity_search.return_value = [Document(page_content="Wind: 12 mph", metadata={})]
    store_b.table = "live_index"

    retriever = Retriever([store_a, store_b], mock_chatbot)
    retriever.retrieve("What is the wind speed?")

    store_a.similarity_search.assert_called_once_with("What is the wind speed?", filter=None)
    store_b.similarity_search.assert_called_once_with("What is the wind speed?", filter=None)


def test_retriever_passes_filter_to_stores(mock_chatbot):
    """Check that a metadata filter is forwarded to every store."""
    store = MagicMock()
    store.similarity_search.return_value = []
    store.table = "live_index"

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("Temperature in Pullman?", filter={"station": "Pullman"})

    store.similarity_search.assert_called_once_with("Temperature in Pullman?", filter={"station": "Pullman"})


def test_retriever_handles_empty_store_results(mock_chatbot):
    """Check that retrieve still calls the chatbot when no documents are returned."""
    store = MagicMock()
    store.similarity_search.return_value = []
    store.table = "live_index"

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("What is the humidity?")

    mock_chatbot.invoke.assert_called_once()


def test_retriever_context_includes_section_label(mock_chatbot):
    """Check that the prompt sent to the chatbot contains a labeled section header."""
    store = MagicMock()
    store.similarity_search.return_value = [Document(page_content="Temp: 65F", metadata={})]
    store.table = "daily_index"

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("Historical temperature?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "[Historical Data]" in prompt_arg


def test_retriever_accepts_single_store(mock_chatbot):
    """Check that Retriever wraps a bare PgVectorStore in a list."""
    from backend.vector_store import PgVectorStore

    store = MagicMock(spec=PgVectorStore)
    store.similarity_search.return_value = []
    store.table = "forecast_index"

    retriever = Retriever(store, mock_chatbot)
    retriever.retrieve("Will it rain tomorrow?")

    store.similarity_search.assert_called_once_with("Will it rain tomorrow?", filter=None)


def test_retriever_prompt_contains_question(mock_vector_store, mock_chatbot):
    """Check that the formatted prompt contains the user's question."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the forecast for Pullman?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "What is the forecast for Pullman?" in prompt_arg


def test_retriever_prompt_contains_context(mock_vector_store, mock_chatbot):
    """Check that the formatted prompt includes document content from the store."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the humidity?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "Humidity: 45%" in prompt_arg
