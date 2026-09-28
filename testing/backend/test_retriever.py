"""Retrieval behavior with separately controlled interpretation and answer calls."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from backend.retriever import Retriever
from backend.weather_query import WeatherQuery
from weather_fixtures import POINT, intent_json, weather_document, weather_stores


def test_valid_interpretation_selects_source_dates_and_renders_sources_once():
    """Use validated constraints and distinct source labels in the final answer."""
    stores, model = weather_stores(), MagicMock()
    stores[0].similarity_search.return_value = [weather_document(), weather_document()]
    model.invoke.side_effect = [intent_json(), "It was 72 F at the nearby source."]
    reply = Retriever(stores, model).retrieve("How warm here on September 9?", point=POINT)
    for store in stores:
        store.similarity_search.assert_called_once_with(
            "Temperature here on 2026-09-09?",
            k=8,
            selection=WeatherQuery(("1",), date(2026, 9, 9), date(2026, 9, 9)),
        )
    assert reply.count("Pullman, Whitman County: 2026-09-09 (observation)") == 1
    assert "may not cover every day" in reply
    prompt = model.invoke.call_args.args[0][0]
    assert "Historical Data" in prompt and "72" in prompt
    assert "latitude" not in prompt and "117.181" not in prompt


@pytest.mark.parametrize("kind,expected", [("observation", [0, 1]), ("forecast", [2]), ("both", [0, 1, 2])])
def test_searches_only_indexes_for_requested_data_kind(kind, expected):
    """Do not pay for irrelevant searches or mix predictions into measured weather."""
    stores, model = weather_stores(), MagicMock()
    model.invoke.return_value = intent_json(data_kind=kind)
    reply = Retriever(stores, model).retrieve("weather?", point=POINT)
    assert "No matching weather records" in reply
    assert [i for i, store in enumerate(stores) if store.similarity_search.called] == expected
    model.invoke.assert_called_once()


def test_missing_map_point_skips_catalog_and_models():
    """An absent point never falls back to searching every station."""
    stores, model = weather_stores(), MagicMock()
    assert "map" in Retriever(stores, model).retrieve("Pullman yesterday")
    for store in stores:
        store.stations.assert_not_called()
        store.similarity_search.assert_not_called()
    model.invoke.assert_not_called()


@pytest.mark.parametrize("location", ["different", "unknown"])
def test_explicit_unknown_location_cannot_use_the_selected_source(location):
    """Do not turn an unresolved Seattle request into Pullman data."""
    stores, model = weather_stores(), MagicMock()
    model.invoke.return_value = intent_json(location=location)
    reply = Retriever(stores, model).retrieve("Seattle on 2026-09-09", point=POINT)
    assert "Choose that point on the map" in reply
    assert all(not store.similarity_search.called for store in stores)
    model.invoke.assert_called_once()


@pytest.mark.parametrize("action", ["clarify", "decline"])
@pytest.mark.parametrize("location", ["selected", "different", "unknown"])
def test_conversational_decisions_skip_retrieval_and_answer_generation(action, location):
    """A request can receive a clarification or refusal before embedding calls."""
    stores, model = weather_stores(), MagicMock()
    model.invoke.return_value = intent_json(
        action=action, location=location, start=None, end=None, question="", message="Please clarify."
    )
    assert Retriever(stores, model).retrieve("unspecified request", point=POINT) == "Please clarify."
    assert all(not store.similarity_search.called for store in stores)
    model.invoke.assert_called_once()


@pytest.mark.parametrize("operation", ["stations", "similarity_search"])
def test_required_database_failure_propagates(operation):
    """A failed source cannot become partial evidence or a no data response."""
    stores, model = weather_stores(), MagicMock()
    model.invoke.return_value = intent_json()
    getattr(stores[1], operation).side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        Retriever(stores, model).retrieve("weather?", point=POINT)
    assert model.invoke.call_count == (0 if operation == "stations" else 1)


def test_forecast_context_never_labels_forecast_time_as_observation():
    """Keep prediction dates separate from measurement timestamps."""
    stores, model = weather_stores(), MagicMock()
    stores[2].similarity_search.return_value = [weather_document()]
    model.invoke.side_effect = [intent_json(data_kind="forecast"), "Forecast: 72 F."]
    reply = Retriever(stores, model).retrieve("forecast?", point=POINT)
    prompt = model.invoke.call_args.args[0][0].split("Context:")[1]
    assert "Observation timestamp" not in prompt
    assert "Forecast dates" in prompt and "(forecast)" in reply


@pytest.mark.parametrize("reply", ["", " \n"])
def test_empty_answer_remains_empty_for_http_validation(reply):
    """Source labels must not conceal an empty provider reply."""
    stores, model = weather_stores(), MagicMock()
    stores[0].similarity_search.return_value = [weather_document()]
    model.invoke.side_effect = [intent_json(), reply]
    assert Retriever(stores, model).retrieve("weather?", point=POINT) == reply
