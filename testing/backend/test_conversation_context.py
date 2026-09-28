"""Persisted context validation and model interpretation of weather follow ups."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from backend.conversation_context import ConversationContext
from backend.retriever import Retriever
from backend.weather_intent import WeatherInterpreter
from history_fixture import structured_mock
from weather_fixtures import POINT, STATION, intent_json, weather_stores


@pytest.mark.parametrize(
    "values",
    [
        {"station_ids": ["unknown"]},
        {"start": "2026-09-01"},
        {"end": "2026-09-01"},
        {"start": "2026-09-02", "end": "2026-09-01"},
        {"subject": " "},
        {"point": {"latitude": 100, "longitude": 0}},
        {"data_kind": "unknown"},
        {"sql": "SELECT 1"},
    ],
)
def test_invalid_persisted_context_is_rejected(values):
    """Reject corrupted state before it reaches retrieval."""
    with pytest.raises(ValueError):
        ConversationContext.model_validate(values)


def test_legacy_context_loads_but_does_not_choose_a_station_for_the_user():
    """Old station identifiers do not replace explicit map selection on a new request."""
    context = ConversationContext.model_validate(
        {
            "station_ids": ["1"],
            "start": "2026-09-09",
            "end": "2026-09-09",
            "subject": "temperature",
        }
    )
    stores, model = weather_stores(), MagicMock()
    turn = Retriever(stores, model).prepare_turn("Humidity?", context)
    assert turn.reply is not None
    assert turn.outcome == "needs_clarification" and "map" in turn.reply
    assert all(not store.stations.called for store in stores)
    model.invoke_json.assert_not_called()


def test_followup_receives_previous_constraints_without_language_parsing():
    """The model sees arbitrary follow ups and validated prior intent."""
    previous = ConversationContext(
        point=POINT,
        station_ids=["1"],
        start=date(2026, 9, 9),
        end=date(2026, 9, 9),
        subject="temperature",
        question="Temperature here on September 9, 2026?",
    )
    model = structured_mock(MagicMock())
    model.invoke.return_value = intent_json(subject="humidity", question="Humidity here on September 9, 2026?")
    turn = Retriever(weather_stores(), model).prepare_turn("And how damp?", previous, today=date(2026, 9, 10))
    assert turn.context.subject == "humidity" and turn.context.start == previous.start
    payload = model.invoke_json.call_args.args[1]
    assert payload["question"] == "And how damp?"
    assert payload["previous_context"]["question"] == previous.question
    assert "station_ids" not in payload["previous_context"]


def test_preparation_freezes_dates_and_does_not_interpret_again_for_answers():
    """Retrying after midnight keeps the accepted period and source."""
    model = structured_mock(MagicMock())
    model.invoke.return_value = intent_json()
    stores = weather_stores()
    retriever = Retriever(stores, model)
    turn = retriever.prepare_turn("Yesterday?", point=POINT, today=date(2026, 9, 10))
    model.invoke_json.side_effect = AssertionError("must not reinterpret")
    for store in stores:
        store.stations.side_effect = AssertionError("must not resolve again")
    result = retriever.answer_result(turn)
    assert result.outcome == "no_data"
    assert all(store.similarity_search.call_args.kwargs["selection"].start == date(2026, 9, 9) for store in stores)


def test_subjects_are_not_a_hardcoded_vocabulary():
    """Structured interpretation may preserve combined measurements and new topics."""
    model = structured_mock(MagicMock())
    model.invoke.return_value = intent_json(subject="evapotranspiration and soil moisture")
    intent = WeatherInterpreter(model).interpret("Water loss?", POINT, STATION)
    assert intent.subject == "evapotranspiration and soil moisture"
    assert json.loads(model.invoke.call_args.args[0][0].split("\nInput JSON:\n")[1])["question"] == "Water loss?"
