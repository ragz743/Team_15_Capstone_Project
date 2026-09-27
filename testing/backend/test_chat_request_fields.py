"""HTTP validation for chat request fields and metadata filters."""

from unittest.mock import MagicMock

import backend.api as api
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


@pytest.mark.parametrize(
    "fields",
    [
        {"debug": True},
        {"filter": {"station": "Pullman", "county": "Whitman", "date": "2026-09-09", "id": "1", "source": "daily"}},
        {"filter": {"station": "a" * 101}},
    ],
    ids=["unexpected-field", "too-many-filters", "long-filter-value"],
)
def test_invalid_chat_fields_are_rejected_before_retrieval(monkeypatch: MonkeyPatch, fields: dict) -> None:
    """Reject unknown request fields and filters exceeding either limit."""
    retriever = MagicMock()
    monkeypatch.setattr(api, "_retriever", retriever)
    payload = {"messages": [{"role": "user", "content": "Weather in Pullman?"}], **fields}

    response = TestClient(api.app).post("/api/chat", json=payload)

    assert response.status_code == 422
    retriever.retrieve.assert_not_called()


@pytest.mark.parametrize(
    "metadata_filter",
    [
        None,
        {},
        {"station": "Pullman", "county": "Whitman", "date": "2026-09-09", "id": "1"},
        {"station": "a" * 100},
    ],
    ids=["omitted", "empty", "four-filters", "maximum-value-length"],
)
def test_valid_chat_filters_reach_retrieval(monkeypatch: MonkeyPatch, metadata_filter: dict[str, str] | None) -> None:
    """Preserve optional filters and accept both exact limits."""
    retriever = MagicMock()
    retriever.retrieve.return_value = "Weather response."
    monkeypatch.setattr(api, "_retriever", retriever)
    payload: dict[str, object] = {"messages": [{"role": "user", "content": "Weather in Pullman?"}]}
    if metadata_filter is not None:
        payload["filter"] = metadata_filter

    response = TestClient(api.app).post("/api/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["reply"] == "Weather response."
    retriever.retrieve.assert_called_once_with("Weather in Pullman?", filter=metadata_filter)
