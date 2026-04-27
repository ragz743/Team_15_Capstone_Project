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
    """Check that retrieve calls the vector store with the question."""
    retriever = Retriever(mock_vector_store, mock_chatbot)
    retriever.retrieve("What is the temperature?")
    mock_vector_store.similarity_search.assert_called_once_with("What is the temperature?")


def test_retriever_calls_chatbot(mock_vector_store, mock_chatbot):
    """Check that retrieve passes a formatted prompt to the chatbot."""
    retriever = Retriever(mock_vector_store, mock_chatbot)
    retriever.retrieve("What is the temperature?")
    mock_chatbot.invoke.assert_called_once()


def test_retriever_returns_chatbot_response(mock_vector_store, mock_chatbot):
    """Check that retrieve returns the chatbot response."""
    retriever = Retriever(mock_vector_store, mock_chatbot)
    response = retriever.retrieve("What is the temperature?")
    assert response == "The temperature at Pullman is 72F."
