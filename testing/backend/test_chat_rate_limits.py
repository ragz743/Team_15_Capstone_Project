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


@pytest.mark.parametrize(
    ("provider_message", "public_message"),
    [
        pytest.param(
            "private provider detail",
            "The answer provider is rate-limiting requests. Please try again later.",
            id="temporary",
        ),
        pytest.param(
            "Rate limit exceeded: free-models-per-day. private provider detail",
            "The model provider's daily free allowance has been reached. Please try again after the allowance resets.",
            id="daily-allowance",
        ),
    ],
)
@pytest.mark.parametrize("provider", ["chat", "embedding"])
def test_provider_rate_limit_returns_service_unavailable(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
    provider: str,
    provider_message: str,
    public_message: str,
) -> None:
    """Return a useful error without exposing provider diagnostics."""
    provider_response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
    error: Exception
    if provider == "chat":
        error = TooManyRequestsResponseError(
            TooManyRequestsResponseErrorData.model_validate({"error": {"code": 429, "message": provider_message}}),
            provider_response,
        )
    else:
        error = RateLimitError(provider_message, response=provider_response, body=None)
    retriever = MagicMock()
    retriever.retrieve.side_effect = error
    monkeypatch.setattr(api, "_retriever", retriever)

    response = TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Weather in Pullman?"}]}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": public_message}
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
