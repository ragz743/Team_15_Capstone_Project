"""Usage metering captures every LLM call made inside the LangGraph chatbot workflow.

Builds the production ChatbotWorkflow through its constructor, the way LangGraphEngine does, and runs its
real graph (classifier -> parallel query nodes via Send -> summarizer). Only the outside world is faked:
fake chat models stand in for OpenRouter and mocked weather databases stand in for AgWeatherNet, so no
network or database is used.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import backend.workflow.workflow as graph_module
import pytest
from backend.analytics.metering import RequestUsage, metered
from backend.databases._awn_connection_base import SchemaQueryResult
from backend.models._chatbot_base import _BaseChatbot
from backend.workflow.workflow import ChatbotWorkflow, ClassifierChatbot
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pytest import MonkeyPatch

_TABLE = "station_100093"
_SQL = (
    f"SELECT TSTAMP, Forecast_time, air_temp FROM `{_TABLE}` "
    "WHERE TSTAMP >= '2026-10-30' AND TSTAMP < '2026-10-31' "
    "AND Forecast_time >= '2026-10-30' AND Forecast_time < '2026-10-31'"
)


def _reply(content: str, model: str, tokens_in: int, tokens_out: int, cost: float | None = None) -> AIMessage:
    """Build a model reply carrying usage the way langchain-openrouter reports it."""
    metadata: dict = {"model_name": model}
    if cost is not None:
        metadata["cost"] = cost
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out},
        response_metadata=metadata,
    )


class _FakeChatbot(_BaseChatbot):
    """_BaseChatbot around a fake LangChain chat model, like the OpenRouter chatbot ModelFactory builds."""

    def __init__(self, reply: AIMessage) -> None:
        self._model = GenericFakeChatModel(messages=itertools.cycle([reply]))

    async def ainvoke(self, messages: list[str]) -> str:
        return str((await self._model.ainvoke(messages)).content)


def _classification(*query_types: str) -> str:
    return json.dumps(
        {"sub_queries": [{"query_type": kind, "reworded_query": f"{kind} question"} for kind in query_types]}
    )


@pytest.fixture
def weather_databases(monkeypatch: MonkeyPatch) -> None:
    """Replace the three AgWeatherNet database connections the workflow opens with mocks."""

    def database(**_kwargs) -> MagicMock:
        db = MagicMock()
        db.format_table_name.return_value = _TABLE
        db.query_schema.return_value = [
            SchemaQueryResult("air_temp", "float", "YES", "", "Temperature"),
            SchemaQueryResult("TSTAMP", "datetime", "YES", "", "Observation time"),
            SchemaQueryResult("Forecast_time", "datetime", "YES", "", "Forecast time"),
        ]
        cursor = db.conn.cursor.return_value.__enter__.return_value
        cursor.description = [("TSTAMP",), ("Forecast_time",), ("air_temp",)]
        cursor.fetchall.return_value = [(datetime(2026, 10, 30, 9), datetime(2026, 10, 30, 9), 54.2)]
        return db

    for name in ("AWNDatabaseConnection", "AWNDailyDatabaseConnection", "AWNForecastDatabaseConnection"):
        monkeypatch.setattr(graph_module, name, database)


def _workflow(classification: str) -> ChatbotWorkflow:
    """Build the production workflow with fake models, wired like LangGraphEngine wires the configured models."""
    classifier = _FakeChatbot(_reply(classification, "vendor/classifier-model", 300, 60))
    chat = _FakeChatbot(_reply(_SQL, "vendor/sql-model", 900, 40, cost=0.0003))
    return ChatbotWorkflow(chat_model=chat, classifier=ClassifierChatbot(classifier))


@pytest.mark.usefixtures("weather_databases")
def test_metering_captures_every_llm_call_in_the_langgraph_workflow() -> None:
    """Classifier, both parallel query nodes, and the summarizer are each recorded once with their tokens."""
    workflow = _workflow(_classification("current_weather", "forecast_weather"))

    usage = RequestUsage()
    with metered(usage):
        workflow.run_result(
            "What's it like now and will it rain tomorrow?",
            station_id=100093,
            reference_time=datetime(2026, 10, 30, tzinfo=UTC),
        )

    calls = sorted((c.model, c.input_tokens, c.output_tokens, c.cost_usd) for c in usage.calls)
    assert calls == [
        ("vendor/classifier-model", 300, 60, None),  # classifier
        ("vendor/sql-model", 900, 40, 0.0003),  # SQL generation, current weather node
        ("vendor/sql-model", 900, 40, 0.0003),  # SQL generation, forecast node (ran in parallel)
        ("vendor/sql-model", 900, 40, 0.0003),  # summarizer
    ]
    assert all(c.succeeded and not c.tokens_estimated for c in usage.calls)


@pytest.mark.usefixtures("weather_databases")
def test_workflow_runs_outside_a_request_are_not_recorded() -> None:
    """Running the workflow without an active request records nothing and does not fail."""
    workflow = _workflow(_classification("miscellaneous"))
    usage = RequestUsage()
    with metered(usage):
        pass
    workflow.run_result("What is a dew point?", station_id=100093, reference_time=datetime(2026, 10, 30, tzinfo=UTC))
    assert usage.calls == []
