"""Interpretation tests use controlled model replies, not language accuracy claims."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from backend.weather_intent import WeatherInterpreter
from history_fixture import structured_mock
from weather_fixtures import POINT, STATION, intent_json


@pytest.mark.parametrize(
    "question",
    [
        "Was it chilly here the day before yesterday?",
        "hw wet was it that day?",
        "And humidity?",
        "Write a sonnet",
        "Seattle on 2026-09-09",
        "rain here excluding Tuesday?",
    ],
)
def test_original_language_reaches_model_without_keyword_gate(question):
    """Pass arbitrary wording and conversation into the model before deciding intent."""
    model = structured_mock(MagicMock())
    model.invoke.return_value = intent_json()
    history = [{"role": "user", "content": "Temperature yesterday?"}]
    WeatherInterpreter(model).interpret(question, POINT, STATION, history=history, today=date(2026, 9, 11))
    prompt = model.invoke.call_args.args[0][0]
    payload = json.loads(prompt.split("\nInput JSON:\n")[1])
    assert payload["question"] == question
    assert payload["conversation"] == history
    assert payload["reference_date"] == "2026-09-11"
    assert payload["selected_point"] == POINT.model_dump()
    assert "117.181" not in prompt
    assert "station_ids" not in payload


@pytest.mark.parametrize("response", ["", "not JSON", "{}", "```json\n{}\n```", intent_json(sql="SELECT 1")])
def test_malformed_provider_response_is_an_error(response):
    """Do not retry with a less constrained query or treat broken output as no data."""
    model = structured_mock(MagicMock())
    model.invoke.return_value = response
    with pytest.raises(ValueError):
        WeatherInterpreter(model).interpret("weather?", POINT, STATION)


def test_provider_failure_propagates():
    """Connection failures must remain service errors."""
    model = structured_mock(MagicMock())
    model.invoke.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        WeatherInterpreter(model).interpret("weather?", POINT, STATION)


@pytest.mark.parametrize("fence", [None, "```json", "```JSON", "```"])
def test_valid_json_accepts_one_optional_code_block(fence):
    """Accept formatting around the JSON without relaxing its schema."""
    response = intent_json()
    model = structured_mock(MagicMock())
    model.invoke.return_value = f"{fence}\n{response}\n```" if fence else response
    result = WeatherInterpreter(model).interpret("Temperature yesterday?", POINT, STATION)
    assert result.action == "query"
    assert result.selection(STATION).station_ids == (STATION.id,)


@pytest.mark.parametrize(
    "response",
    [
        "Answer:\n" + intent_json(),
        intent_json() + "\nExtra text",
        "```python\n" + intent_json() + "\n```",
        "```json\n" + intent_json(sql="SELECT 1") + "\n```",
    ],
)
def test_surrounding_prose_and_extra_fields_are_rejected(response):
    """Only a complete JSON object with the expected fields can execute."""
    model = structured_mock(MagicMock())
    model.invoke.return_value = response
    with pytest.raises(ValueError):
        WeatherInterpreter(model).interpret("Temperature yesterday?", POINT, STATION)
