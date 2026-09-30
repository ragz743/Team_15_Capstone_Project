"""Exercise the web adapter and Gavin's graph without external model or source calls."""

from datetime import datetime
from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.chat_turn import PreparedChatTurn
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.weather_query import RequestedPoint, Station
from backend.workflow.contracts import WorkflowTimeoutError
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


def test_missing_location_does_not_run_graph(weather):
    """A missing selection asks the user for a point without generating SQL."""
    engine, runtime = weather
    turn = engine.prepare_turn("Temperature today", reference_time=REFERENCE)
    assert turn.outcome == "needs_clarification" and "map" in turn.reply
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
        "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily",
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
