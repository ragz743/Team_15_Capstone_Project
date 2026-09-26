"""History interpretation, validation and evidence contracts without live model calls."""

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from backend.chat_turn import PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.history_models import HistoryEntry, HistoryIntent, HistorySnapshot
from backend.history_service import HistoryService
from history_fixture import structured_mock
from pydantic import ValidationError

NOW = datetime(2026, 9, 22, 7, 30, tzinfo=UTC)


def setup_history(*outputs):
    """Inject model replies and an owned record; all behavior after inference is real."""
    model, store = structured_mock(MagicMock()), MagicMock()
    model.invoke.side_effect = [json.dumps(output) for output in outputs]
    store.history_window.return_value = [{"user": "Remind me about our chat", "assistant": "Which topic?"}]
    store.search_history.return_value = [
        {
            "title": "Frost discussion",
            "requested_at": NOW,
            "user_content": "Was there frost in January?",
            "assistant_content": "The saved reply discussed freezing.",
            "context": None,
        }
    ]
    return HistoryService(model, "fixture"), model, store


def test_raw_paraphrase_and_clarification_context_reach_model_before_routing():
    """No regex vocabulary gate stands between a free-form message and the interpreter."""
    service, model, store = setup_history({"action": "recall", "terms": ["frost", "freezing"]})
    question = "the frezing one we chatted abt"
    owner, conversation = uuid4(), uuid4()
    result = service.prepare(store, owner, conversation, question, accepted_at=NOW)
    prompt = model.invoke.call_args.args[0][0]
    assert question in prompt and "Which topic?" in prompt
    assert "2026-09-22T00:30:00-07:00" in prompt
    assert str(owner) not in prompt and str(conversation) not in prompt
    assert result.snapshot is not None
    assert result.snapshot.entries[0].question == "Was there frost in January?"
    store.search_history.assert_called_once_with(
        owner, conversation, before=NOW, scope="all", terms=["frost", "freezing"], start=None, end=None
    )


@pytest.mark.parametrize("action", ["weather", "clarify"])
def test_non_recall_routes_do_not_search_saved_history(action):
    """A new weather request or a real ambiguity does not trigger a broad history read."""
    output = {"action": action}
    if action == "clarify":
        output["clarification"] = "Which September did you mean?"
    service, model, store = setup_history(output)
    model.invoke.side_effect = None
    model.invoke.return_value = json.dumps(output)
    result = service.prepare(store, uuid4(), uuid4(), "some input", accepted_at=NOW)
    assert result.intent.action == action
    store.search_history.assert_not_called()


@pytest.mark.parametrize(
    "output",
    [
        {"action": "recall", "owner_id": "someone-else"},
        {"action": "recall", "sql": "SELECT * FROM conversations"},
        {"action": "recall", "terms": [""]},
        {"action": "recall", "start": "2026-09-22"},
        {"action": "recall", "start": "2026-09-22", "end": "2026-09-01"},
        {"action": "reuse"},
        {"action": "clarify"},
    ],
)
def test_invalid_model_plans_cannot_read_history(output):
    """The model cannot choose ownership, SQL or an invalid date range."""
    service, model, store = setup_history(output)
    model.invoke.side_effect = None
    model.invoke.return_value = json.dumps(output)
    with pytest.raises(ValidationError):
        service.prepare(store, uuid4(), uuid4(), "Find a chat", accepted_at=NOW)
    store.search_history.assert_not_called()


def test_conversation_dates_use_local_day_boundaries():
    """Date searches remain correct on the daylight-saving transition day."""
    service, _, store = setup_history({"action": "recall", "start": "2026-11-01", "end": "2026-11-01"})
    service.prepare(store, uuid4(), uuid4(), "November first chat", accepted_at=NOW)
    args = store.search_history.call_args.kwargs
    assert args["start"].date() == date(2026, 11, 1)
    assert (args["end"].astimezone(UTC) - args["start"].astimezone(UTC)).total_seconds() == 25 * 3600


def test_empty_search_skips_history_answer_model():
    """No matching records produce an honest reply without asking a model to invent memory."""
    service, model, store = setup_history({"action": "recall"})
    store.search_history.return_value = []
    result = service.prepare(store, uuid4(), uuid4(), "Our old chat?", accepted_at=NOW)
    assert result.snapshot is not None
    assert "could not find" in service.answer("Our old chat?", result.snapshot)
    assert model.invoke.call_count == 1


def test_history_answer_has_real_dates_citations_and_saved_excerpts():
    """A readable summary is accompanied by verifiable original messages, not new weather."""
    service, _, store = setup_history(
        {"action": "recall"},
        {"statements": [{"text": "We discussed frost in January.", "refs": [1]}]},
    )
    snapshot = service.prepare(store, uuid4(), uuid4(), "What was that chat?", accepted_at=NOW).snapshot
    assert snapshot is not None
    answer = service.answer("What was that chat?", snapshot)
    assert "[1] 2026-09-22 00:30 PDT" in answer
    assert "You asked: Was there frost in January?" in answer
    assert "not updated weather" in answer and "We discussed frost" in answer


def test_fabricated_references_are_rejected():
    """An invented citation cannot be persisted as a successful history answer."""
    service, _, store = setup_history(
        {"action": "recall"}, {"statements": [{"text": "Unsupported claim", "refs": [999]}]}
    )
    snapshot = service.prepare(store, uuid4(), uuid4(), "Recall?", accepted_at=NOW).snapshot
    assert snapshot is not None
    with pytest.raises(ValueError, match="unavailable evidence"):
        service.answer("Recall?", snapshot)


def test_reuse_passes_saved_context_but_never_saved_answer_to_weather():
    """The history model supplies a new question; backend validated context selects fresh data."""
    service, _, store = setup_history({"action": "reuse", "terms": ["frost"], "weather_question": "Humidity today?"})
    store.search_history.return_value[0]["context"] = ConversationContext(
        station_ids=["1"], start=date(2026, 1, 1), end=date(2026, 1, 1), subject="frost"
    ).model_dump(mode="json")
    result = service.prepare(store, uuid4(), uuid4(), "Same place as the frost chat, humidity today?", accepted_at=NOW)
    assert result.context is not None
    assert result.context.station_ids == ["1"] and result.reply is None and result.snapshot is None
    assert result.intent.weather_question == "Humidity today?"


def test_history_snapshot_round_trip_and_weather_separation():
    """Old completed snapshots still load; new history evidence survives retry serialization."""
    snapshot = HistorySnapshot(
        intent=HistoryIntent(action="recall"),
        as_of=NOW,
        entries=[HistoryEntry(ref=1, title="Saved", asked_at=NOW, question="Frost?", answer=None)],
    )
    prepared = PreparedChatTurn(
        outcome="history", question="Remember?", context=ConversationContext(), history=snapshot
    )
    assert PreparedChatTurn.model_validate_json(prepared.model_dump_json()) == prepared
    old = PreparedChatTurn(outcome="history", question="Remember?", context=ConversationContext(), reply="Old reply")
    assert PreparedChatTurn.model_validate_json(old.model_dump_json()).reply == "Old reply"
    with pytest.raises(ValidationError):
        PreparedChatTurn(outcome="no_data", question="Remember?", context=ConversationContext(), history=snapshot)


def test_history_limits_are_explicit_and_failed_questions_keep_no_reply():
    """Large results are labelled as a subset; no answer is fabricated for failed turns."""
    service, model, store = setup_history(
        {"action": "recall"}, {"statements": [{"text": "You asked about frost.", "refs": [1]}]}
    )
    store.search_history.return_value[0]["assistant_content"] = None
    store.search_history.return_value *= 13
    snapshot = service.prepare(store, uuid4(), uuid4(), "Recap", accepted_at=NOW).snapshot
    assert snapshot is not None
    assert snapshot.truncated and len(snapshot.entries) == 12
    reply = service.answer("Recap", snapshot)
    assert "12 most recent" in reply and "No completed reply was saved" in reply
    assert '"answer": null' in model.invoke.call_args.args[0][0]


@pytest.mark.parametrize("response", ["not JSON", "{}", "x" * 16001])
def test_invalid_provider_output_is_an_error_not_a_no_history_result(response):
    """Failures never masquerade as a successful empty search."""
    service, model, store = setup_history()
    model.invoke.side_effect = None
    model.invoke.return_value = response
    with pytest.raises(ValueError):
        service.prepare(store, uuid4(), uuid4(), "Recall", accepted_at=NOW)
    store.search_history.assert_not_called()


def test_malformed_json_gets_one_bounded_repair_before_any_search():
    """A schema repair uses the same input and cannot bypass validation."""
    service, model, store = setup_history()
    model.invoke.side_effect = ["not JSON", '{"action":"recall","terms":["frost"]}']
    result = service.prepare(store, uuid4(), uuid4(), "Find my frost chat", accepted_at=NOW)
    assert result.snapshot is not None
    assert result.snapshot.intent.terms == ["frost"]
    assert model.invoke.call_count == 2 and store.search_history.call_count == 1
    assert "output_error" in model.invoke.call_args.args[0][0]
