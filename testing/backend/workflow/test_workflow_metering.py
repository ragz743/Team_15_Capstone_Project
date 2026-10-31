"""Usage metering captures every LLM call made inside the LangGraph chatbot workflow.

Runs the real compiled graph (classifier -> parallel query nodes via Send -> summarizer) with fake
chat models standing in for OpenRouter and mocked weather databases, so no network or database is used.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from time import monotonic
from unittest.mock import MagicMock

from backend.analytics.metering import RequestUsage, metered
from backend.databases._awn_connection_base import SchemaQueryResult
from backend.models._chatbot_base import _BaseChatbot
from backend.workflow.workflow import (
    ChatbotWorkflow,
    ClassifierChatbot,
    QueryClassification,
    QueryClassifications,
)
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

_TABLE = "station_100093"


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


class _FakeWorkflowChatbot(_BaseChatbot):
    """_BaseChatbot wrapper around a fake LangChain chat model, like ModelFactory's chatbots."""

    def __init__(self) -> None:
        self._model = GenericFakeChatModel(
            messages=itertools.cycle(
                [
                    _reply(
                        f"SELECT air_temp FROM `{_TABLE}` "
                        "WHERE TSTAMP >= '2026-10-30' AND TSTAMP < '2026-10-31' "
                        "AND Forecast_time >= '2026-10-30' AND Forecast_time < '2026-10-31'",
                        "vendor/sql-model",
                        900,
                        40,
                        cost=0.0003,
                    )
                ]
            )
        )

    async def ainvoke(self, messages: list[str]) -> str:
        # like ChatbotOpenRouter, sync invoke() comes from _BaseChatbot and runs this in its own event loop
        return str((await self._model.ainvoke(messages)).content)


def _workflow(sub_queries: list[QueryClassification]) -> ChatbotWorkflow:
    """Build the real graph without opening database or OpenRouter connections."""
    workflow = object.__new__(ChatbotWorkflow)
    workflow.checkpointer = InMemorySaver()
    workflow._debug = False
    workflow._deadline = monotonic() + 90
    workflow._query_handlers = {
        "current_weather": "_query_current",
        "forecast_weather": "_query_forecast",
        "historical_weather": "_query_historical",
        "miscellaneous": "_query_miscellaneous",
    }
    workflow.graph = workflow._build_graph()

    # classifier: a chat model followed by a parser, the same shape as with_structured_output()
    classifier = object.__new__(ClassifierChatbot)
    classifier._injected_model = None
    fake_classifier_model = GenericFakeChatModel(messages=iter([_reply("{}", "openrouter/free", 300, 60)]))
    classifier._model = fake_classifier_model | RunnableLambda(lambda _: QueryClassifications(sub_queries=sub_queries))
    workflow.classifier_chat_model = classifier
    workflow.workflow_chat_model = _FakeWorkflowChatbot()

    for name in ("current_db", "forecast_db", "historical_daily_db"):
        db = MagicMock()
        db.format_table_name.return_value = _TABLE
        db.query_schema.return_value = [
            SchemaQueryResult("air_temp", "float", "YES", "", "Temperature"),
            SchemaQueryResult("TSTAMP", "datetime", "YES", "", "Observation time"),
            SchemaQueryResult("Forecast_time", "datetime", "YES", "", "Forecast time"),
        ]
        cursor = db.conn.cursor.return_value.__enter__.return_value
        cursor.description = [("air_temp",)]
        cursor.fetchall.return_value = [(54.2,)]
        db.simple_query.return_value = iter([(54.2,)])
        setattr(workflow, name, db)
    workflow._nearest_station_search = MagicMock(return_value=100093)
    return workflow


def test_metering_captures_every_llm_call_in_the_langgraph_workflow() -> None:
    """Classifier, both parallel query nodes, and the summarizer are each recorded once with their tokens."""
    workflow = _workflow(
        [
            QueryClassification(query_type="current_weather", reworded_query="What is the temperature now?"),
            QueryClassification(query_type="forecast_weather", reworded_query="Will it rain tomorrow?"),
        ]
    )

    usage = RequestUsage()
    with metered(usage):
        workflow.run_result(
            "What's it like now and will it rain tomorrow?",
            station_id=100093,
            reference_time=datetime(2026, 10, 30, tzinfo=UTC),
        )

    calls = sorted((c.model, c.input_tokens, c.output_tokens, c.cost_usd) for c in usage.calls)
    assert calls == [
        ("openrouter/free", 300, 60, None),  # classifier (structured output)
        ("vendor/sql-model", 900, 40, 0.0003),  # SQL generation, current weather node
        ("vendor/sql-model", 900, 40, 0.0003),  # SQL generation, forecast node (ran in parallel)
        ("vendor/sql-model", 900, 40, 0.0003),  # summarizer
    ]
    assert all(c.kind == "chat" and c.succeeded and not c.tokens_estimated for c in usage.calls)


def test_workflow_runs_outside_a_request_are_not_recorded() -> None:
    """Running the workflow without an active request records nothing and does not fail."""
    workflow = _workflow([QueryClassification(query_type="miscellaneous", reworded_query="What is a dew point?")])
    usage = RequestUsage()
    with metered(usage):
        pass
    workflow.run("What is a dew point?", (46.73, -117.15), "whitman")
    assert usage.calls == []
