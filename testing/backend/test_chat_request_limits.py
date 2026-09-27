"""HTTP boundary checks for chat request sizes."""

from unittest.mock import MagicMock

import backend.api as api
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


@pytest.mark.parametrize(
    "lengths",
    [(4001,), (1,) * 41, (4000,) * 8 + (1,)],
    ids=["message", "message-count", "transcript"],
)
def test_oversized_chat_is_rejected_before_retrieval(monkeypatch: MonkeyPatch, lengths: tuple[int, ...]) -> None:
    """Reject each exceeded limit before invoking the retriever."""
    retriever = MagicMock()
    monkeypatch.setattr(api, "_retriever", retriever)
    messages = [{"role": "user", "content": "a" * length} for length in lengths]

    response = TestClient(api.app).post("/api/chat", json={"messages": messages})

    assert response.status_code == 422
    retriever.retrieve.assert_not_called()


@pytest.mark.parametrize(
    "lengths",
    [(4000,), (1,) * 40, (4000,) * 8],
    ids=["message", "message-count", "transcript"],
)
def test_chat_at_each_size_limit_is_accepted(monkeypatch: MonkeyPatch, lengths: tuple[int, ...]) -> None:
    """Accept the exact limits and preserve the latest user message."""
    retriever = MagicMock()
    retriever.retrieve.return_value = "Weather response."
    monkeypatch.setattr(api, "_retriever", retriever)
    messages = [{"role": "user", "content": "a" * length} for length in lengths]

    response = TestClient(api.app).post("/api/chat", json={"messages": messages})

    assert response.status_code == 200
    assert response.json()["reply"] == "Weather response."
    retriever.retrieve.assert_called_once_with(messages[-1]["content"], filter=None)
