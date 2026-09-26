"""Provider JSON configuration is mandatory and never silently downgraded to free text."""

from unittest.mock import MagicMock

import pytest
from backend.history_models import HistoryIntent
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from langchain_core.messages import HumanMessage, SystemMessage


def test_zero_retries_really_disables_sdk_backoff(monkeypatch):
    """Prevent the SDK's UNSET default from extending a bounded history call for an hour."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key")
    model = ChatbotOpenRouter({"model": "fixture-model", "request_timeout": 25000, "max_retries": 0})
    assert model._model.client.sdk_configuration.retry_config is None
    assert model._model.client.sdk_configuration.timeout_ms == 25000


def test_json_model_requires_all_fields_and_supported_provider():
    """Separate instructions from user data and require explicit nullable search fields."""
    model = ChatbotOpenRouter.__new__(ChatbotOpenRouter)
    model._model = MagicMock()
    model._model.invoke.return_value.content = '{"action":"weather"}'
    schema = HistoryIntent.model_json_schema()
    original_required = list(schema["required"])
    assert model.invoke_json("Interpret only.", {"message": "arbitrary user wording"}, schema) == '{"action":"weather"}'
    args, kwargs = model._model.invoke.call_args
    assert isinstance(args[0][0], SystemMessage) and isinstance(args[0][1], HumanMessage)
    assert "arbitrary user wording" in args[0][1].content
    output = kwargs["response_format"]["json_schema"]
    assert output["strict"] is True
    assert set(output["schema"]["required"]) == set(schema["properties"])
    assert kwargs["provider"] == {"require_parameters": True, "allow_fallbacks": False}
    assert schema["required"] == original_required


def test_json_provider_failure_does_not_fall_back_or_change_models():
    """An unsupported provider capability must surface as an error."""
    model = ChatbotOpenRouter.__new__(ChatbotOpenRouter)
    model._model = MagicMock()
    model._model.invoke.side_effect = TimeoutError("fixture failure")
    with pytest.raises(TimeoutError):
        model.invoke_json("Interpret only.", {}, HistoryIntent.model_json_schema())
    assert model._model.invoke.call_count == 1
