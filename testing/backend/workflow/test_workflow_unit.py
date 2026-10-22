"""Unit tests for the chatbot workflow."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, NamedTuple, cast

import pytest
from backend.databases._awn_connection_base import SchemaQueryResult
from backend.workflow import workflow as workflow_module
from backend.workflow.workflow import (
    ChatbotWorkflow,
    ChatState,
    ClassifierChatbot,
    QueryClassification,
    QueryType,
)
from langgraph.checkpoint.memory import InMemorySaver
from mysql.connector.errors import ProgrammingError


class FakeDatabase:
    """Database double for query generation tests."""

    def __init__(self, schema: list[SchemaQueryResult] | None = None) -> None:
        """Set up schema, query recording, and deterministic results."""
        self.schema = schema or []
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.results: list[tuple[Any, ...]] = [("72 F",)]
        self.failures = 0

    def format_table_name(self, station_id: int) -> str:
        """Return a deterministic station table name."""
        return f"station_{station_id}"

    def query_schema(self, table_name: str) -> list[SchemaQueryResult]:
        """Return the configured schema for the selected station."""
        assert table_name == "station_123"
        return self.schema

    def simple_query(self, query: str, params: tuple[Any, ...]) -> Iterator[tuple[Any, ...]]:
        """Record SQL and return results or raise a configured database error."""
        self.queries.append((query, params))
        if self.failures:
            self.failures -= 1
            raise ProgrammingError("unknown column")
        return iter(self.results)


class FakeGraph:
    """Graph double that records initial state and config."""

    def __init__(self) -> None:
        """Initialize captured invocation values."""
        self.initial_state: ChatState | None = None
        self.config: dict[str, Any] | None = None

    def invoke(self, initial_state: ChatState, config: dict[str, Any]) -> dict[str, Any]:
        """Record graph inputs and return a deterministic assistant message."""
        self.initial_state = initial_state
        self.config = config
        return {"messages": [SimpleNamespace(content="answer")]}


class SampleRow(NamedTuple):
    """Schema row for markdown conversion."""

    column: str


def make_workflow(debug: bool = False) -> ChatbotWorkflow:
    """Construct a workflow without opening database or model connections."""
    chatbot = object.__new__(ChatbotWorkflow)
    chatbot._debug = debug
    chatbot._query_handlers = {
        "current_weather": "_query_current",
        "forecast_weather": "_query_forecast",
        "historical_weather": "_query_historical",
        "miscellaneous": "_query_miscellaneous",
    }
    return chatbot


def make_state(*queries: QueryClassification) -> ChatState:
    """Create a minimal workflow state."""
    return {
        "messages": [("user", "original question")],
        "sub_queries": list(queries),
        "nearest_station_id": 123,
        "original_user_input": "original question",
    }


def test_classifier_uses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify classifier prompts the structured model and returns its subqueries."""
    expected = [QueryClassification(query_type="current_weather", reworded_query="Current weather?")]
    calls: list[list[tuple[str, str]]] = []

    class FakeStructuredModel:
        def with_structured_output(self, output_type: type) -> FakeStructuredModel:
            assert output_type is workflow_module.QueryClassifications
            return self

        def invoke(self, messages: list[tuple[str, str]]) -> SimpleNamespace:
            calls.append(messages)
            return SimpleNamespace(sub_queries=expected)

    monkeypatch.setattr(workflow_module, "ChatOpenRouter", lambda **kwargs: FakeStructuredModel())
    classifier = ClassifierChatbot()

    assert classifier.classify(make_state()) == {"sub_queries": expected}
    assert calls[0][-1] == ("user", "original question")


def test_workflow_initialization_builds_graph_with_injected_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify initialization wires graph, model, and database dependencies."""
    database_instances = [SimpleNamespace(conn=object()) for _ in range(3)]
    database_factories = iter(database_instances)
    monkeypatch.setattr(workflow_module, "AWNDatabaseConnection", lambda: next(database_factories))
    monkeypatch.setattr(workflow_module, "AWNDailyDatabaseConnection", lambda: next(database_factories))
    monkeypatch.setattr(workflow_module, "AWNForecastDatabaseConnection", lambda: next(database_factories))
    monkeypatch.setattr(workflow_module, "ClassifierChatbot", lambda: "classifier")
    monkeypatch.setattr(workflow_module.ModelFactory, "load_from_models_yaml", lambda: ("embedding", "chatbot"))
    checkpoint = InMemorySaver()

    chatbot = ChatbotWorkflow(checkpointer=checkpoint)

    assert chatbot.checkpointer is checkpoint
    assert chatbot.classifier_chat_model == "classifier"
    assert chatbot.workflow_chat_model == "chatbot"
    assert chatbot.current_db is database_instances[0]
    assert chatbot.historical_daily_db is database_instances[1]
    assert chatbot.forecast_db is database_instances[2]
    assert {
        "_query_classifier",
        "_query_historical",
        "_query_current",
        "_query_forecast",
        "_query_miscellaneous",
        "_chatbot_summarize",
    }.issubset(chatbot.graph.get_graph().nodes)


def test_close_disconnects_only_connected_databases() -> None:
    """Close active database connections and leave inactive ones alone."""
    chatbot = make_workflow()
    calls: list[str] = []
    chatbot.current_db = cast(
        Any,
        SimpleNamespace(conn=SimpleNamespace(is_connected=lambda: True, disconnect=lambda: calls.append("current"))),
    )
    chatbot.forecast_db = cast(
        Any,
        SimpleNamespace(conn=SimpleNamespace(is_connected=lambda: False, disconnect=lambda: calls.append("forecast"))),
    )
    chatbot.historical_daily_db = cast(
        Any,
        SimpleNamespace(conn=SimpleNamespace(is_connected=lambda: True, disconnect=lambda: calls.append("historical"))),
    )

    chatbot.close()

    assert calls == ["current", "historical"]


def test_run_passes_station_and_user_question_to_graph() -> None:
    """Check run finds a station, invokes the graph, and returns its answer."""
    chatbot = make_workflow()
    chatbot._nearest_station_search = cast(Any, lambda coords, county: 456)
    chatbot.graph = cast(Any, FakeGraph())

    answer = chatbot.run("Question", (46.0, -117.0), "Whitman")

    assert answer == "answer"
    assert chatbot.graph.initial_state["nearest_station_id"] == 456
    assert chatbot.graph.initial_state["original_user_input"] == "Question"
    assert chatbot.graph.config == {"configurable": {"thread_id": "TEMP_KEY_REPLACE_ME"}}


@pytest.mark.parametrize("rows", [[], iter(())])
def test_nearest_station_search_raises_when_county_has_no_stations(rows: Any) -> None:
    """Raise a clear error when the metadata query returns no station."""
    chatbot = make_workflow()
    chatbot.current_db = cast(Any, SimpleNamespace(simple_query=lambda query, params: rows))

    with pytest.raises(ValueError, match="No nearest station returned"):
        chatbot._nearest_station_search((46.0, -117.0), "Whitman")


def test_nearest_station_search_returns_integer_station_id() -> None:
    """Convert the closest station identifier returned by the database."""
    chatbot = make_workflow()
    chatbot.current_db = cast(Any, SimpleNamespace(simple_query=lambda query, params: iter([("123", 2.5)])))

    assert chatbot._nearest_station_search((46.0, -117.0), "Whitman") == 123


def test_query_classifier_delegates_and_logs_state_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure classifier result is returned and passed to debug logging."""
    chatbot = make_workflow(debug=True)
    update = {"sub_queries": []}
    chatbot.classifier_chat_model = cast(Any, SimpleNamespace(classify=lambda state: update))
    log_calls: list[tuple[str, ChatState, dict]] = []
    monkeypatch.setattr(
        chatbot,
        "_log_state_update",
        lambda node, state, result: log_calls.append((node, state, result)),
    )
    state = make_state()

    assert chatbot._query_classifier(state) == update
    assert log_calls == [("_query_classifier", state, update)]


@pytest.mark.parametrize(
    ("node", "kind", "db_attribute"),
    [
        ("_query_current", "current_weather", "current_db"),
        ("_query_forecast", "forecast_weather", "forecast_db"),
        ("_query_historical", "historical_weather", "historical_daily_db"),
    ],
)
def test_weather_nodes_skip_unmatched_and_delegate_matching_queries(
    monkeypatch: pytest.MonkeyPatch,
    node: str,
    kind: QueryType,
    db_attribute: str,
) -> None:
    """Check each weather node skips unrelated queries and delegates matching ones."""
    chatbot = make_workflow()
    database = object()
    setattr(chatbot, db_attribute, cast(Any, database))
    query = QueryClassification(query_type=kind, reworded_query="Weather?")
    invoked: list[tuple[list[QueryClassification], ChatState, object, str]] = []
    monkeypatch.setattr(
        chatbot,
        "_run_generated_query",
        lambda queries, state, db, name: invoked.append((queries, state, db, name)) or {"messages": []},
    )
    state = make_state()

    assert getattr(chatbot, node)(state) == {}
    state["sub_queries"] = [query]
    assert getattr(chatbot, node)(state) == {"messages": []}
    assert invoked == [([query], state, database, node)]


def test_miscellaneous_node_answers_without_database_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose multi-part miscellaneous questions and return the model response."""
    chatbot = make_workflow()
    prompts: list[str] = []
    chatbot.workflow_chat_model = cast(
        Any, SimpleNamespace(invoke=lambda messages: prompts.append(messages[0]) or "answer")
    )
    first = QueryClassification(query_type="miscellaneous", reworded_query="What is dew point?")
    second = QueryClassification(query_type="miscellaneous", reworded_query="What is humidity?")
    state = make_state(first, second)

    assert chatbot._query_miscellaneous(state) == {"messages": [("assistant", "answer")]}
    assert "What is dew point?\nWhat is humidity?" in prompts[0]
    assert (
        chatbot._query_miscellaneous(
            make_state(QueryClassification(query_type="current_weather", reworded_query="Current?"))
        )
        == {}
    )


def test_run_generated_query_formats_schema_and_results() -> None:
    """Generate a valid query, execute it, and format results for summarization."""
    chatbot = make_workflow()
    database = FakeDatabase([SchemaQueryResult("air_temp", "float", "YES", "", "Temperature")])
    chatbot.current_db = cast(Any, database)
    prompts: list[str] = []
    chatbot.workflow_chat_model = cast(
        Any, SimpleNamespace(invoke=lambda messages: prompts.append(messages[0]) or "SELECT air_temp FROM station_123;")
    )
    queries = [QueryClassification(query_type="current_weather", reworded_query="What is current temperature?")]

    update = chatbot._run_generated_query(queries, make_state(*queries), cast(Any, database), "_query_current")

    assert database.queries == [("SELECT air_temp FROM station_123", ())]
    assert "air_temp" in prompts[0]
    assert "SQL query used:\nSELECT air_temp FROM station_123" in update["messages"][0][1]
    assert "('72 F',)" in update["messages"][0][1]


def test_run_generated_query_retries_programming_error_with_error_context() -> None:
    """Provide the previous database error to the model before retrying."""
    chatbot = make_workflow()
    database = FakeDatabase()
    database.failures = 1
    chatbot.current_db = cast(Any, database)
    prompts: list[str] = []
    chatbot.workflow_chat_model = cast(
        Any, SimpleNamespace(invoke=lambda messages: prompts.append(messages[0]) or "SELECT * FROM station_123")
    )
    query = QueryClassification(query_type="current_weather", reworded_query="Temperature?")

    chatbot._run_generated_query([query], make_state(query), cast(Any, database), "_query_current")

    assert len(database.queries) == 2
    assert "unknown column" in prompts[1]
    assert "SELECT * FROM station_123" in prompts[1]


@pytest.mark.parametrize(
    ("node_name", "database_attribute", "query_type"),
    [
        ("_query_current", "current_db", "current_weather"),
        ("_query_historical", "historical_daily_db", "historical_weather"),
        ("_query_forecast", "forecast_db", "forecast_weather"),
    ],
)
def test_run_generated_query_selects_database_for_each_weather_node(
    node_name: str,
    database_attribute: str,
    query_type: QueryType,
) -> None:
    """Resolve the matching workflow database for each supported query node."""
    chatbot = make_workflow()
    database = FakeDatabase()
    setattr(chatbot, database_attribute, cast(Any, database))
    chatbot.workflow_chat_model = cast(Any, SimpleNamespace(invoke=lambda messages: "SELECT * FROM station_123"))
    query = QueryClassification(query_type=query_type, reworded_query="Weather?")

    result = chatbot._run_generated_query([query], make_state(query), cast(Any, database), node_name)

    assert database.queries == [("SELECT * FROM station_123", ())]
    assert "Database results:" in result["messages"][0][1]


def test_run_generated_query_raises_after_final_database_failure() -> None:
    """Propagate the database error when all bounded SQL retries fail."""
    chatbot = make_workflow()
    database = FakeDatabase()
    database.failures = chatbot._MAX_SQL_ATTEMPTS
    chatbot.current_db = cast(Any, database)
    chatbot.workflow_chat_model = cast(Any, SimpleNamespace(invoke=lambda messages: "SELECT * FROM station_123"))
    query = QueryClassification(query_type="current_weather", reworded_query="Weather?")

    with pytest.raises(ProgrammingError, match="unknown column"):
        chatbot._run_generated_query([query], make_state(query), cast(Any, database), "_query_current")

    assert len(database.queries) == chatbot._MAX_SQL_ATTEMPTS


def test_run_generated_query_fails_if_retry_limit_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail explicitly if configuration prevents all query attempts."""
    chatbot = make_workflow()
    monkeypatch.setattr(chatbot, "_MAX_SQL_ATTEMPTS", 0)
    database = FakeDatabase()
    chatbot.current_db = cast(Any, database)
    query = QueryClassification(query_type="current_weather", reworded_query="Weather?")

    with pytest.raises(RuntimeError, match="attempts ended without a result"):
        chatbot._run_generated_query([query], make_state(query), cast(Any, database), "_query_current")


def test_run_generated_query_rejects_unknown_node() -> None:
    """Reject query generation requests from an unrecognized workflow node."""
    chatbot = make_workflow()
    database = FakeDatabase()

    with pytest.raises(ValueError, match="unrecognized query node"):
        chatbot._run_generated_query(
            [QueryClassification(query_type="current_weather", reworded_query="Temperature?")],
            make_state(),
            cast(Any, database),
            "_query_other",
        )


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("DELETE FROM station_123", "must be a SELECT"),
        ("SELECT * FROM station_123; DROP TABLE station_123", "only one statement"),
        ("SELECT * FROM another_station", "references a table"),
        ("SELECT 1", "references a table"),
    ],
)
def test_validate_generated_query_rejects_unsafe_or_unscoped_sql(query: str, message: str) -> None:
    """Reject non-SELECT, multi-statement, and wrong-table model output."""
    with pytest.raises(ProgrammingError, match=message):
        ChatbotWorkflow._validate_generated_query(query, "station_123")


def test_validate_generated_query_accepts_case_and_backticks() -> None:
    """Allow case-insensitive SELECT and the selected table quoted with backticks."""
    ChatbotWorkflow._validate_generated_query(" select * from `STATION_123` ", "station_123")


def test_sub_queries_result_message_and_routing() -> None:
    """Filter subqueries, format empty results, and route supported query types."""
    current = QueryClassification(query_type="current_weather", reworded_query="Temperature?")
    misc = QueryClassification(query_type="miscellaneous", reworded_query="Define dew point.")
    state = make_state(current, misc)

    assert ChatbotWorkflow._sub_queries_for(state, "current_weather") == [current]
    result = ChatbotWorkflow._query_result_message([current], "SELECT 1", [])
    assert "No matching weather data was found." in result["messages"][0][1]

    chatbot = make_workflow()
    sends = chatbot._route_query(state)
    assert [send.node for send in sends] == ["_query_current", "_query_miscellaneous"]


def test_summarize_uses_context_and_returns_assistant_message() -> None:
    """Pass accumulated context to the model and return the resulting answer."""
    chatbot = make_workflow()
    prompts: list[str] = []
    chatbot.workflow_chat_model = cast(
        Any, SimpleNamespace(invoke=lambda messages: prompts.append(messages[0]) or "summary")
    )
    state = make_state()
    state["messages"] = [("user", "original question"), ("assistant", "72 F")]

    assert chatbot._chatbot_summarize(state) == {"messages": [("assistant", "summary")]}
    assert "72 F" in prompts[0]
    assert "original question" in prompts[0]


def test_debug_logging_and_message_content(caplog: pytest.LogCaptureFixture) -> None:
    """Log state changes only in debug mode and normalize message shapes."""
    chatbot = make_workflow(debug=True)
    state = make_state()
    chatbot._log_state_update("_query_current", state, {"messages": [("assistant", "result")]})

    assert "chat_state_update" in caplog.text
    assert ChatbotWorkflow._message_content(SimpleNamespace(content=72)) == "72"
    assert ChatbotWorkflow._message_content(("assistant", "tuple content")) == "tuple content"
    assert ChatbotWorkflow._message_content("plain content") == "plain content"

    quiet = make_workflow(debug=False)
    with caplog.at_level("INFO"):
        quiet._log_event("node", "event", "details")
    assert "node=node" not in caplog.text
