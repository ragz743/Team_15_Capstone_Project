"""Opt-in checks of weather interpretation using synthetic map requests."""

import os
from datetime import date

import dotenv
import pytest
from backend.conversation_context import ConversationContext
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.weather_intent import WeatherInterpreter
from backend.weather_query import RequestedPoint, Station

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_WEATHER_MODEL_TESTS") != "1", reason="Opt-in external weather-model evaluation"
)
POINT = RequestedPoint(latitude=46.73, longitude=-117.18)
STATION = Station("1", "Pullman", "Whitman")
REFERENCE_DATE = date(2026, 9, 11)


@pytest.fixture(scope="module")
def interpreter():
    """Use the configured free model with bounded calls and no provider fallback."""
    dotenv.load_dotenv()
    model_name = os.environ["OPENROUTER_CHAT_MODEL"]
    assert model_name == "openrouter/free" or model_name.endswith(":free"), (
        "This evaluation only authorizes a free chat model"
    )
    model = ChatbotOpenRouter(
        {"model": model_name, "temperature": 0, "max_tokens": 1800, "request_timeout": 25000, "max_retries": 0}
    )
    return WeatherInterpreter(model)


def test_relative_date_and_paraphrase(interpreter):
    """Resolve a casual weather question against the supplied reference date."""
    intent = interpreter.interpret("How warm did it get here yesterday?", POINT, STATION, today=REFERENCE_DATE)
    assert intent.action == "query" and intent.location == "selected"
    assert intent.data_kind == "observation"
    assert intent.start == intent.end == date(2026, 9, 10)


def test_follow_up_keeps_prior_period(interpreter):
    """Change the measurement without changing the validated date or map location."""
    context = ConversationContext(
        point=POINT, start=date(2026, 9, 8), end=date(2026, 9, 8), subject="temperature", data_kind="observation"
    )
    intent = interpreter.interpret("And how humid was it?", POINT, STATION, context=context, today=REFERENCE_DATE)
    assert intent.action == "query" and intent.location == "selected"
    assert intent.start == intent.end == date(2026, 9, 8)
    assert intent.data_kind == "observation"


def test_different_place_requires_map_change(interpreter):
    """A named location cannot silently reuse the selected point in another city."""
    intent = interpreter.interpret(
        "What was the temperature in Seattle yesterday?", POINT, STATION, today=REFERENCE_DATE
    )
    assert intent.action != "query" or intent.location != "selected"
