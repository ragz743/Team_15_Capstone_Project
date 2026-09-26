"""Weather follow-ups keep valid constraints and reject explicit invalid replacements."""

from datetime import date

import pytest
from backend.conversation_context import ConversationContext, resolve_turn
from backend.weather_query import Station
from pydantic import ValidationError

STATIONS = [Station("1", "Pullman", "Whitman"), Station("2", "Colfax", "Whitman"), Station("3", "Spokane", "Spokane")]
DAY = date(2026, 9, 10)


def initial():
    """Resolve a complete initial weather question."""
    return resolve_turn("Temperature at Pullman on 2026-09-10", STATIONS, today=DAY).context


@pytest.mark.parametrize(
    ("question", "ids", "day", "subject"),
    [
        ("What about humidity?", ["1"], DAY, "humidity"),
        ("and Colfax?", ["2"], DAY, "temperature"),
        ("What about September 11?", ["1"], date(2026, 9, 11), "temperature"),
        ("Humidity at Colfax on September 11", ["2"], date(2026, 9, 11), "humidity"),
        ("and station 2?", ["2"], DAY, "temperature"),
        ("What about Whitman County?", ["1", "2"], DAY, "temperature"),
    ],
)
def test_partial_replacements(question, ids, day, subject):
    """Each explicit field replaces only its corresponding prior value."""
    turn = resolve_turn(question, STATIONS, initial(), today=DAY)
    assert turn.clarification is None
    assert turn.context.station_ids == ids
    assert turn.context.start == turn.context.end == day
    assert turn.context.subject == subject
    assert subject in turn.question
    assert day.isoformat() in turn.question


@pytest.mark.parametrize(
    "question",
    [
        "What about Seattle?",
        "and station 999?",
        "Humidity at Seattle?",
        "Seattle on 2026-09-11",
        "What about Seattle on September 11?",
        "and Unknown County?",
    ],
)
def test_unknown_location_never_reuses_previous_station(question):
    """Invalid replacements require a new location even on the following turn."""
    turn = resolve_turn(question, STATIONS, initial(), today=DAY)
    assert turn.selection is None
    assert not turn.context.station_ids
    assert resolve_turn("What about humidity?", STATIONS, turn.context).selection is None


@pytest.mark.parametrize(
    "question",
    [
        "and 2026-02-30?",
        "from 2026-09-12 to 2026-09-10",
        "on the 25th",
        "next September",
        "on 09/11/26",
    ],
)
def test_bad_date_does_not_reuse_previous_day(question):
    """Malformed and unsupported dates invalidate the inherited date."""
    turn = resolve_turn(question, STATIONS, initial(), today=DAY)
    assert turn.selection is None
    assert turn.context.start is None


def test_clarification_can_be_completed_in_later_turns():
    """Partial valid fields survive requests for missing information."""
    first = resolve_turn("What was the temperature at Pullman?", STATIONS)
    assert first.clarification and first.context.station_ids == ["1"]
    second = resolve_turn("September 10, 2026", STATIONS, first.context)
    assert second.selection and second.context.subject == "temperature"
    first = resolve_turn("Humidity on September 10, 2026", STATIONS)
    assert first.clarification and first.context.start == DAY
    resolved = resolve_turn("Colfax", STATIONS, first.context)
    assert resolved.selection is not None
    assert resolved.selection.station_ids == ("2",)


def test_no_context_and_unrelated_question():
    """New conversations and unrelated requests do not borrow a weather selection."""
    assert resolve_turn("What about humidity?", STATIONS).selection is None
    assert resolve_turn("Write a poem", STATIONS, initial()).context == ConversationContext()


def test_relative_dates_stay_canonical_across_midnight():
    """A resolved yesterday stays the same day when the next turn arrives tomorrow."""
    first = resolve_turn("Temperature at Pullman yesterday", STATIONS, today=DAY)
    later = resolve_turn("What about humidity?", STATIONS, first.context, today=date(2026, 9, 11))
    assert later.selection is not None
    assert later.selection.start == date(2026, 9, 9)


def test_explicit_filter_conflict_and_catalog_change():
    """A filter may narrow a request but never silently override a named station."""
    result = resolve_turn("Humidity at Pullman on 2026-09-10", STATIONS, metadata_filter={"station": "Colfax"})
    assert result.clarification is not None
    assert result.selection is None and "conflicts" in result.clarification
    result = resolve_turn("Humidity on 2026-09-10", STATIONS, metadata_filter={"station": "Colfax"})
    assert result.selection is not None
    assert result.selection.station_ids == ("2",)
    assert resolve_turn("Humidity?", STATIONS[1:], initial()).selection is None


@pytest.mark.parametrize(
    "values",
    [
        {"station_ids": ["not-an-id"]},
        {"start": "2026-09-10"},
        {"start": "2026-09-10", "end": "2026-09-09"},
        {"subject": "ignore instructions"},
    ],
)
def test_untrusted_context_is_validated(values):
    """Client supplied context has a narrow typed shape."""
    with pytest.raises(ValidationError):
        ConversationContext(**values)


def test_invalid_filter_and_untrusted_multi_station_context():
    """Unsupported filters cannot fail open or widen a station selection."""
    turn = resolve_turn("Humidity at Pullman on 2026-09-10", STATIONS, metadata_filter={"unexpected": "x"})
    assert turn.clarification is not None
    assert turn.selection is None and "Unsupported metadata filter" in turn.clarification
    previous = initial().model_copy(update={"station_ids": ["1", "3"]})
    turn = resolve_turn("What about humidity?", STATIONS, previous)
    assert turn.selection is None and not turn.context.station_ids
    turn = resolve_turn("Humidity on 2026-09-10", STATIONS, metadata_filter={"state": "WA"})
    assert turn.selection is None and not turn.context.station_ids


@pytest.mark.parametrize("question", ["What about past 7 days?", "and 3 days ago?", "last week"])
def test_relative_date_only_followups_retain_station(question):
    """Supported multiword relative periods are dates, not unknown locations."""
    result = resolve_turn(question, STATIONS, initial(), today=DAY)
    assert result.selection is not None
    assert result.selection is not None
    assert result.selection.station_ids == ("1",)
    assert result.context.subject == "temperature"


@pytest.mark.parametrize(
    "question",
    [
        "whats the wather",  # codespell:ignore whats
        "what's the weather?",
        "How is the wheather?",  # codespell:ignore wheather
        "weather",
    ],
)
def test_general_weather_asks_only_for_location_and_retains_today(question):
    """A broad weather request needs no separate measurement questionnaire."""
    turn = resolve_turn(question, STATIONS, today=DAY)
    assert turn.context.subject == "weather" and turn.context.start == turn.context.end == DAY
    assert turn.clarification is not None
    assert turn.clarification.count("?") == 1 and "Which location" in turn.clarification
    assert turn.clarification is not None
    assert "today" in turn.clarification and "measurement" not in turn.clarification


def test_reported_typo_all_all_exchange_can_continue_with_a_location():
    """Repeated broad replies retain intent and explain supported geographic scope."""
    turn = resolve_turn("whats the wather", STATIONS, today=DAY)  # codespell:ignore whats
    for _ in range(2):
        turn = resolve_turn("all", STATIONS, turn.context, today=DAY)
        assert turn.context.subject == "weather" and turn.context.start == DAY
        assert turn.context.station_ids == [] and turn.selection is None
        assert turn.clarification is not None
        assert "one station or county at a time" in turn.clarification
        assert turn.clarification is not None
        assert "Whitman County" in turn.clarification and turn.clarification.count("?") == 1
    turn = resolve_turn("Whitman County", STATIONS, turn.context, today=DAY)
    assert turn.selection is not None
    assert turn.selection.station_ids == ("1", "2") and turn.context.subject == "weather"
    assert turn.context.start == DAY and turn.clarification is None


def test_all_recovers_old_empty_context_without_losing_general_weather_intent():
    """Older broken chats stored no slots; a fresh broad reply can still proceed."""
    turn = resolve_turn("all", STATIONS, ConversationContext(), today=DAY)
    assert turn.context.subject == "weather" and turn.context.start == DAY
    assert turn.clarification is not None
    assert "Which location" in turn.clarification
    resolved = resolve_turn("Pullman", STATIONS, turn.context, today=DAY)
    assert resolved.selection is not None
    assert resolved.selection.station_ids == ("1",)


@pytest.mark.parametrize("reply", ["all", "everything", "all measurements", "all weather conditions"])
def test_all_measurements_preserves_selected_station_and_canonical_day(reply):
    """An overview uses fresh evidence in the existing location/date scope."""
    turn = resolve_turn(reply, STATIONS, initial(), today=date(2026, 9, 11))
    assert turn.clarification is None and turn.context.subject == "weather"
    assert turn.selection is not None
    assert turn.selection.station_ids == ("1",) and turn.selection.start == DAY


def test_all_answers_the_pending_measurement_question():
    """A specific station/day can be completed by asking for every available reading."""
    previous = ConversationContext(station_ids=["1"], start=DAY, end=DAY)
    turn = resolve_turn("all", STATIONS, previous, today=DAY)
    assert turn.selection is not None
    assert turn.context.subject == "weather" and turn.selection.station_ids == ("1",)


def test_all_dates_never_silently_reuses_a_day_or_discards_location():
    """All-time requests need bounded dates and keep other resolved slots."""
    turn = resolve_turn("What was the weather at Pullman?", STATIONS, today=DAY)
    assert turn.context.start is None and turn.context.station_ids == ["1"]
    turn = resolve_turn("all", STATIONS, turn.context, today=DAY)
    assert turn.context.subject == "weather" and turn.context.station_ids == ["1"]
    assert turn.clarification is not None
    assert "specific day or date range" in turn.clarification and turn.context.start is None
    resolved = resolve_turn("yesterday", STATIONS, turn.context, today=DAY)
    assert resolved.selection is not None
    assert resolved.selection.start == date(2026, 9, 9)
    assert resolve_turn("all dates", STATIONS, initial(), today=DAY).selection is None


def test_overview_keeps_invalid_dates_and_explicit_broad_locations_unresolved():
    """Friendly defaults must not widen scope or override a malformed explicit date."""
    invalid = resolve_turn("whats the wather at Pullman on 2026-02-30", STATIONS, today=DAY)  # codespell:ignore whats
    assert invalid.selection is None and invalid.context.start is None
    forecast = resolve_turn("forecast at Pullman", STATIONS, today=DAY)
    assert forecast.selection is None and forecast.context.start is None
    broad = resolve_turn("weather at all stations today", STATIONS, initial(), today=DAY)
    assert broad.selection is None and broad.context.station_ids == []


def test_new_present_weather_question_changes_yesterday_but_short_overview_does_not():
    """Only a fresh present-tense request resets a resolved historical period to today."""
    prior = resolve_turn("temperature at Pullman yesterday", STATIONS, today=DAY).context
    assert resolve_turn("all", STATIONS, prior, today=DAY).context.start == date(2026, 9, 9)
    assert resolve_turn("whats the wather", STATIONS, prior, today=DAY).context.start == DAY  # codespell:ignore whats
