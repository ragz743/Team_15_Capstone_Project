"""Exercise the web adapter and Gavin's graph without external model or source calls."""

from datetime import datetime
from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.chat_turn import PreparedChatTurn
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.weather_query import RequestedPoint, Station
from backend.workflow.contracts import WorkflowClassificationError, WorkflowTimeoutError
from backend.workflow.engine import LangGraphEngine
from workflow_fixture import make_graph

REFERENCE = datetime(2026, 9, 30, 9, tzinfo=TIMEZONE)
POINT = RequestedPoint(latitude=46.7, longitude=-117.1)


@pytest.fixture
def weather(monkeypatch):
    """Connect the real graph to controlled source records and model replies."""
    runtime = make_graph(monkeypatch)
    directory = MagicMock()
    directory.stations.return_value = [Station("1", "Pullman", "Whitman", "46.7", "-117.1", "WA")]
    engine = LangGraphEngine(runtime.model, runtime.classifier, directory=directory)
    return engine, runtime


def test_selected_point_and_raw_question_reach_graph(weather):
    """Location selection never replaces the classifier with a weather or date parser."""
    engine, runtime = weather
    question = "Compare the overnight chill with the afternoon warmth"
    turn = engine.prepare_turn(question, point=POINT, reference_time=REFERENCE)
    restored = PreparedChatTurn.model_validate_json(turn.model_dump_json())
    assert restored.workflow is not None
    assert restored.context.station_ids == ["1"] and restored.workflow.reference_time == REFERENCE
    result = engine.answer_result(restored)
    assert result.outcome == "success" and "70.25" in result.reply
    assert result.sources[0].station == "Pullman" and result.sources[0].times == ["2026-09-29"]
    assert result.coverage == "subset"
    assert "Source station: Pullman, Whitman County." in result.reply
    prompt = runtime.model.invoke.call_args.args[0][0]
    assert "station1daily" not in prompt and "(ID 1)" not in prompt
    assert "Identify stations by name and county" in prompt
    supplied = runtime.classifier.invoke_json.call_args.args[1]
    assert supplied["question"] == question and "46.7" not in str(supplied)
    assert "LIMIT 200" in runtime.cursor.execute.call_args.args[0]
    runtime.database.conn.shutdown.assert_called()


def test_followup_preserves_selected_station_and_dated_history(weather):
    """A saved followup reaches the classifier without looking up a new location."""
    engine, runtime = weather
    history = [{"user": "Temperature yesterday?", "assistant": "70 F.", "asked_at": REFERENCE.isoformat()}]
    turn = engine.prepare_turn(
        "What about humidity?",
        ConversationContext(station_ids=["1"], point=POINT),
        reference_time=REFERENCE,
        history=history,
    )
    engine.answer_result(turn)
    supplied = runtime.classifier.invoke_json.call_args.args[1]
    assert supplied["history"] == history and supplied["question"] == "What about humidity?"


def test_picker_selection_reaches_graph_without_a_coordinate_lookup(weather):
    """A chosen station takes precedence over a previously saved map location."""
    engine, runtime = weather
    engine._catalog.resolve = MagicMock(side_effect=AssertionError("Unexpected coordinate lookup"))
    turn = engine.prepare_turn(
        "Temperature yesterday?", ConversationContext(station_ids=["99"], point=POINT), station_id="1"
    )
    assert turn.context.station_ids == ["1"] and turn.context.point is None
    assert engine.answer_result(turn).outcome == "success"
    assert runtime.classifier.invoke_json.call_args.args[1]["question"] == "Temperature yesterday?"


def test_unknown_picker_station_does_not_run_graph(weather):
    """A station must still exist in the authoritative directory when submitted."""
    engine, runtime = weather
    turn = engine.prepare_turn("Temperature?", station_id="99")
    assert turn.outcome == "needs_clarification" and "no longer available" in turn.reply
    runtime.classifier.invoke_json.assert_not_called()


def test_missing_location_does_not_run_graph(weather):
    """A missing selection asks the user for a point without generating SQL."""
    engine, runtime = weather
    turn = engine.prepare_turn("Temperature today", reference_time=REFERENCE)
    assert turn.outcome == "needs_clarification" and "Browse stations" in turn.reply
    runtime.classifier.invoke_json.assert_not_called()
    runtime.model.invoke.assert_not_called()


def test_empty_records_return_no_data_without_answer_generation(weather):
    """No observations cannot become a plausible model answer."""
    engine, runtime = weather
    runtime.cursor.fetchall.return_value = []
    result = engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    assert result.outcome == "no_data" and "No matching" in result.reply
    assert runtime.model.invoke.call_count == 1


def test_failure_closes_graph_and_does_not_fall_back(weather):
    """A provider timeout remains an error with the request resources closed."""
    engine, runtime = weather
    runtime.classifier.invoke_json.side_effect = TimeoutError("private detail")
    with pytest.raises(WorkflowTimeoutError):
        engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    runtime.model.invoke.assert_not_called()
    runtime.cursor.execute.assert_not_called()
    runtime.database.conn.shutdown.assert_called()


def test_sql_repair_rejects_writes_before_executing_a_select(weather):
    """Only the repaired SELECT reaches the database cursor."""
    engine, runtime = weather
    runtime.model.invoke.side_effect = [
        "DELETE FROM station1daily",
        "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29'",
        "70.25 F.",
    ]
    engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    runtime.cursor.execute.assert_called_once()
    assert runtime.cursor.execute.call_args.args[0].startswith("SELECT")


def test_graph_startup_does_not_require_embeddings(monkeypatch):
    """The web service creates only answer and classifier models."""
    for key in ("AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "fixture")
    monkeypatch.delenv("OPENROUTER_EMBEDDING_MODEL", raising=False)
    model = MagicMock()
    monkeypatch.setattr(api, "ChatbotOpenRouter", model)
    engine, _, _, embedding = api._build_retriever()
    assert isinstance(engine, LangGraphEngine) and embedding == "" and model.call_count == 2


def test_source_connection_starts_read_only_with_a_statement_limit(monkeypatch):
    """Enforce read-only behavior in the database in addition to SQL validation."""
    connection = MagicMock()
    monkeypatch.setattr("backend.databases._awn_connection_base.connector.MySQLConnection", connection)
    with AWNDatabaseConnection(statement_timeout=8):
        pass
    cursor = connection.return_value.cursor.return_value.__enter__.return_value
    assert cursor.execute.call_args_list[0].args == ("SET SESSION max_statement_time = %s", (8,))
    assert cursor.execute.call_args_list[1].args == ("START TRANSACTION READ ONLY",)
    connection.return_value.disconnect.assert_called_once()


@pytest.mark.parametrize("invalid", ["not JSON", '{"sub_queries":[{"query_type":"today"}]}'])
def test_classifier_repairs_once_with_original_inputs(weather, invalid):
    """A schema repair keeps the original question, station and recent context."""
    engine, runtime = weather
    valid = runtime.classifier.invoke_json.return_value
    runtime.classifier.invoke_json.side_effect = [invalid, valid]
    turn = engine.prepare_turn("Temperature today?", point=POINT, reference_time=REFERENCE)
    assert engine.answer_result(turn).outcome == "success"
    first, second = [call.args[1] for call in runtime.classifier.invoke_json.call_args_list]
    assert second == {**first, "output_error": second["output_error"]}
    assert all("input" not in error for error in second["output_error"])


def test_invalid_classifier_stops_after_one_repair(weather):
    """Repeated invalid plans never reach SQL generation or execution."""
    engine, runtime = weather
    runtime.classifier.invoke_json.return_value = "not JSON"
    with pytest.raises(WorkflowClassificationError):
        engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    assert runtime.classifier.invoke_json.call_count == 2
    runtime.model.invoke.assert_not_called()
    runtime.cursor.execute.assert_not_called()


def test_classifier_transport_error_is_not_repaired(weather):
    """Provider failures return without another classifier call."""
    engine, runtime = weather
    runtime.classifier.invoke_json.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    runtime.classifier.invoke_json.assert_called_once()
    runtime.cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("query_type", "date_column", "rejected"),
    [
        ("historical_weather", "JULDATE", "SELECT AVG(AVG_AIR_TEMP) FROM station1daily"),
        (
            "historical_weather",
            "JULDATE",
            "SELECT AVG_AIR_TEMP FROM station1daily WHERE JULDATE >= '2000-01-01' AND JULDATE < '2026-09-30'",
        ),
        (
            "historical_weather",
            "JULDATE",
            "SELECT AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29' OR 1 = 1",
        ),
        ("current_weather", "TSTAMP", "SELECT AVG_AIR_TEMP FROM station1daily WHERE TSTAMP >= CURRENT_DATE"),
        ("current_weather", "TSTAMP", "SELECT AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29'"),
        ("forecast_weather", "Forecast_time", "SELECT AVG_AIR_TEMP FROM station1daily WHERE Init_time = '2026-09-29'"),
    ],
)
def test_invalid_date_scope_is_repaired_before_reading_weather(weather, query_type, date_column, rejected):
    """Only the repaired period on the category's date column reaches the cursor."""
    import json

    from backend.databases._awn_connection_base import SchemaQueryResult

    engine, runtime = weather
    runtime.database.query_schema.return_value.extend(
        [SchemaQueryResult(name, "datetime", "YES", "", "") for name in ("TSTAMP", "Forecast_time", "Init_time")]
    )
    runtime.classifier.invoke_json.return_value = json.dumps(
        {
            "sub_queries": [
                {"query_type": query_type, "reworded_query": "Temperature on September 29, 2026"},
            ]
        }
    )
    corrected = (
        f"SELECT {date_column}, AVG_AIR_TEMP FROM station1daily "
        f"WHERE {date_column} >= '2026-09-29' AND {date_column} < '2026-09-30'"
    )
    runtime.model.invoke.side_effect = [rejected, corrected, "70.25 F."]
    engine.answer_result(engine.prepare_turn("Temperature?", point=POINT, reference_time=REFERENCE))
    runtime.cursor.execute.assert_called_once()
    assert runtime.cursor.execute.call_args.args[0] == corrected + " LIMIT 200"
    assert "previous SQL attempt failed" in runtime.model.invoke.call_args_list[1].args[0][0]


def test_repeated_unbounded_sql_stops_without_a_database_read(weather):
    """Validation failures share the existing three attempt SQL repair budget."""
    from mysql.connector.errors import ProgrammingError

    engine, runtime = weather
    runtime.model.invoke.side_effect = None
    runtime.model.invoke.return_value = "SELECT AVG(AVG_AIR_TEMP) FROM station1daily"
    with pytest.raises(ProgrammingError, match="Bound JULDATE"):
        engine.answer_result(engine.prepare_turn("Temperature?", point=POINT))
    assert runtime.model.invoke.call_count == 3
    runtime.cursor.execute.assert_not_called()


def test_missing_measurement_skips_database_execution(weather):
    """An explicit unavailable measurement returns no data without scanning a table."""
    engine, runtime = weather
    runtime.model.invoke.side_effect = None
    runtime.model.invoke.return_value = "SELECT NULL AS unavailable"
    result = engine.answer_result(engine.prepare_turn("Unsupported measurement?", point=POINT))
    assert result.outcome == "no_data" and not result.sources
    runtime.model.invoke.assert_called_once()
    runtime.cursor.execute.assert_not_called()


def test_retry_after_midnight_rejects_database_clock_and_keeps_original_reference(weather, monkeypatch):
    """A later retry can only execute the repaired literal query using frozen inputs."""
    import backend.workflow.workflow as graph_module

    engine, runtime = weather
    accepted = datetime(2026, 9, 29, 23, 59, tzinfo=TIMEZONE)
    prepared = engine.prepare_turn("Temperature today?", point=POINT, reference_time=accepted)
    runtime.classifier.invoke_json.side_effect = RuntimeError("Provider unavailable")
    with pytest.raises(RuntimeError):
        engine.answer_result(prepared)

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 1, tzinfo=tz)

    monkeypatch.setattr(graph_module, "datetime", NextDay)
    runtime.classifier.invoke_json.side_effect = None
    runtime.model.invoke.side_effect = [
        "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily WHERE JULDATE = CURRENT_DATE",
        "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29'",
        "70.25 F.",
    ]
    restored = PreparedChatTurn.model_validate_json(prepared.model_dump_json())
    engine.answer_result(restored)
    assert runtime.classifier.invoke_json.call_args.args[1]["reference_time"] == accepted.isoformat()
    runtime.cursor.execute.assert_called_once()
    assert "'2026-09-29'" in runtime.cursor.execute.call_args.args[0]
    assert "CURRENT_DATE" not in runtime.cursor.execute.call_args.args[0]
    assert accepted.isoformat() in runtime.model.invoke.call_args_list[1].args[0][0]
