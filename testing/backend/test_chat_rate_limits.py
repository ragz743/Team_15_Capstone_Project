"""Provider rate-limit handling at the chat API boundary."""

from unittest.mock import MagicMock

import backend.api as api
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError
from openrouter.errors import (
    TooManyRequestsResponseError,
    TooManyRequestsResponseErrorData,
)
from pytest import LogCaptureFixture, MonkeyPatch


@pytest.mark.parametrize("provider", ["chat", "embedding"])
def test_provider_rate_limit_returns_service_unavailable(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture, provider: str
) -> None:
    """Return a useful error without exposing provider diagnostics."""
    provider_response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
    error: Exception
    if provider == "chat":
        error = TooManyRequestsResponseError(
            TooManyRequestsResponseErrorData.model_validate(
                {"error": {"code": 429, "message": "private provider detail"}}
            ),
            provider_response,
        )
    else:
        error = RateLimitError("private provider detail", response=provider_response, body=None)
    retriever = MagicMock()
    retriever.retrieve.side_effect = error
    monkeypatch.setattr(api, "_retriever", retriever)

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Weather in Pullman?"}]}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "The answer provider is rate-limiting requests. Please try again later."}
    assert "private provider detail" not in response.text
    assert "private provider detail" not in caplog.text
    retriever.retrieve.assert_called_once_with("Weather in Pullman?", filter=None)


def test_other_retrieval_errors_keep_generic_response(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture) -> None:
    """Classify provider exceptions by type rather than matching arbitrary error text."""
    retriever = MagicMock()
    retriever.retrieve.side_effect = RuntimeError("429 private provider detail")
    monkeypatch.setattr(api, "_retriever", retriever)

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Weather in Pullman?"}]}
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "The weather service could not complete your request. Please try again."}
    assert "private provider detail" not in response.text
    assert "private provider detail" not in caplog.text
    retriever.retrieve.assert_called_once_with("Weather in Pullman?", filter=None)
