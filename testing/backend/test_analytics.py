"""Unit tests for usage metering, cost recording, request tracking, and the admin metrics endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.analytics import admin_api
from backend.analytics.metering import LlmCall, RequestUsage, metered
from backend.analytics.usage_store import (
    UsageStore,
    UsageStoreUnavailableError,
    UsageTracker,
)
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mysql.connector.errors import DatabaseError
from pytest import MonkeyPatch


def _fake_chat(message: AIMessage) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([message]))


# ---------- metering ----------


def test_metered_records_reported_chat_tokens() -> None:
    """Provider reported token usage and model name are recorded for chat calls."""
    usage = RequestUsage()
    model = _fake_chat(
        AIMessage(
            content="72°F in Pullman",
            usage_metadata={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128},
            response_metadata={"model_name": "openai/gpt-oss-20b:free"},
        )
    )
    with metered(usage):
        model.invoke(["What is the temperature in Pullman?"])

    [call] = usage.calls
    assert (call.model, call.input_tokens, call.output_tokens) == ("openai/gpt-oss-20b:free", 120, 8)
    assert not call.tokens_estimated
    assert call.succeeded


def test_metered_records_the_cost_openrouter_reports() -> None:
    """The cost OpenRouter includes in each response is recorded as the call's cost."""
    usage = RequestUsage()
    with metered(usage):
        _fake_chat(AIMessage(content="hi", response_metadata={"model_name": "m", "cost": 0.0042})).invoke(["hi"])

    [call] = usage.calls
    assert call.cost_usd == 0.0042


def test_metered_estimates_tokens_when_not_reported() -> None:
    """Calls without usage metadata fall back to a character based estimate."""
    usage = RequestUsage()
    with metered(usage):
        _fake_chat(AIMessage(content="12345678")).invoke(["1234"])

    [call] = usage.calls
    assert call.tokens_estimated
    assert (call.input_tokens, call.output_tokens) == (1, 2)


def test_calls_outside_metered_block_are_not_recorded() -> None:
    """Model calls made outside a request are ignored."""
    usage = RequestUsage()
    with metered(usage):
        pass
    _fake_chat(AIMessage(content="hi")).invoke(["hi"])
    assert usage.calls == []


# ---------- usage store (no database) ----------


def test_store_records_the_reported_cost_and_zero_when_not_reported() -> None:
    """A reported cost is stored as is; a call without one is stored at $0 and flagged as not reported."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    store = UsageStore(lambda: conn)
    usage = RequestUsage(status="ok")
    usage.calls = [
        LlmCall(model="paid/model", called_at=usage.started_at, input_tokens=1_000, cost_usd=0.0042),
        LlmCall(model="free/model:free", called_at=usage.started_at, cost_usd=0.0),
        LlmCall(model="local/model", called_at=usage.started_at, input_tokens=1_000),
    ]
    store.record(usage)

    [rows] = [c.args[1] for c in cursor.executemany.call_args_list]
    # columns: cost_usd, priced, cost_reported
    assert [row[6:9] for row in rows] == [(0.0042, True, True), (0.0, True, True), (0.0, False, False)]


def test_store_backs_off_after_the_database_is_unreachable() -> None:
    """After a failed connect, writes are skipped quickly instead of every request waiting on the database."""
    connect = MagicMock(side_effect=DatabaseError(msg="Can't connect to MySQL server", errno=2003))
    store = UsageStore(connect)

    with pytest.raises(DatabaseError):
        store.record(RequestUsage(status="ok"))
    attempts = connect.call_count

    with pytest.raises(UsageStoreUnavailableError):
        store.record(RequestUsage(status="ok"))
    assert connect.call_count == attempts  # no new connection attempt during the back-off

    # the tracker treats the back-off as a skipped write, not a failure of the chat request
    with UsageTracker(store).track(None, None) as usage:
        usage.status = "ok"


# ---------- request tracking ----------


def test_tracker_records_status_latency_and_calls() -> None:
    """A tracked request is recorded once with its status and calls."""
    store = MagicMock()
    with UsageTracker(store).track("user-1", "session-1") as usage:
        usage.calls.append(LlmCall(model="m", called_at=usage.started_at))
        usage.status = "ok"

    [recorded] = [c.args[0] for c in store.record.call_args_list]
    assert (recorded.user_id, recorded.session_id, recorded.status) == ("user-1", "session-1", "ok")
    assert recorded.latency_ms >= 0
    assert len(recorded.calls) == 1


def test_tracker_marks_unhandled_exceptions_as_errors() -> None:
    """An exception without an explicit status is recorded as an error with its type name."""
    store = MagicMock()
    with pytest.raises(ValueError), UsageTracker(store).track(None, None):
        raise ValueError("boom")

    recorded = store.record.call_args.args[0]
    assert (recorded.status, recorded.error_type) == ("error", "ValueError")


def test_tracker_skips_requests_marked_not_to_record() -> None:
    """Requests flagged record=False, such as invalid input, are not stored."""
    store = MagicMock()
    with UsageTracker(store).track(None, None) as usage:
        usage.record = False
    store.record.assert_not_called()


def test_tracker_never_fails_the_request_when_recording_fails() -> None:
    """A database failure while recording is logged, not raised."""
    store = MagicMock()
    store.record.side_effect = RuntimeError("database down")
    with UsageTracker(store).track(None, None) as usage:
        usage.status = "ok"


# ---------- /api/chat integration ----------


class _Retriever:
    def __init__(self, reply: str = "answer", error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error

    def retrieve(self, question: str, **kwargs) -> str:
        if self._error is not None:
            raise self._error
        return self._reply


def _post_chat(headers: dict[str, str] | None = None, content: str = "Weather in Pullman?"):
    return TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": content}]}, headers=headers or {}
    )


@pytest.fixture
def recorded(monkeypatch: MonkeyPatch) -> MagicMock:
    """Replace the API's usage tracker with one writing to a mock store."""
    store = MagicMock()
    monkeypatch.setattr(api, "_usage_tracker", UsageTracker(store))
    return store


def test_chat_records_user_and_session_headers(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Valid client ids from headers are recorded with a successful request."""
    monkeypatch.setattr(api, "_retriever", _Retriever())
    response = _post_chat({"X-AWN-User-Id": "browser-123", "X-AWN-Session-Id": "conv_9"})

    assert response.status_code == 200
    usage = recorded.record.call_args.args[0]
    assert (usage.user_id, usage.session_id, usage.status) == ("browser-123", "conv_9", "ok")


def test_chat_ignores_malformed_client_ids(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Header values outside the allowed id format are dropped rather than stored."""
    monkeypatch.setattr(api, "_retriever", _Retriever())
    _post_chat({"X-AWN-User-Id": "x" * 65, "X-AWN-Session-Id": "has spaces"})

    usage = recorded.record.call_args.args[0]
    assert (usage.user_id, usage.session_id) == (None, None)


def test_chat_records_failures_and_skips_invalid_input(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Retriever failures are recorded as errors; empty questions are not recorded at all."""
    monkeypatch.setattr(api, "_retriever", _Retriever(error=RuntimeError("db")))
    assert _post_chat().status_code == 502
    usage = recorded.record.call_args.args[0]
    assert (usage.status, usage.error_type) == ("error", "RuntimeError")

    recorded.reset_mock()
    assert _post_chat(content="   ").status_code == 400
    recorded.record.assert_not_called()


def test_chat_records_unavailable_service(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Requests arriving while the retriever is down count as unavailable."""
    monkeypatch.setattr(api, "_retriever", None)
    assert _post_chat().status_code == 503
    assert recorded.record.call_args.args[0].status == "unavailable"


# ---------- /api/admin/metrics ----------


@pytest.fixture
def admin_store(monkeypatch: MonkeyPatch):
    """Configure an admin token and a fake usage store."""
    monkeypatch.setenv("AWN_ADMIN_TOKEN", "s3cret")
    store = MagicMock()
    store.metrics.return_value = {"summary": {"calls": 3}, "budget": {}}
    monkeypatch.setattr(admin_api, "_usage_store", store)
    return store


def test_admin_metrics_requires_configured_token(monkeypatch: MonkeyPatch, admin_store: MagicMock) -> None:
    """Without AWN_ADMIN_TOKEN the dashboard is disabled rather than open."""
    monkeypatch.delenv("AWN_ADMIN_TOKEN")
    response = TestClient(api.app).get("/api/admin/metrics", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    admin_store.metrics.assert_not_called()


@pytest.mark.parametrize("header", [None, "Bearer wrong", "s3cret", "Basic s3cret"])
def test_admin_metrics_rejects_bad_tokens(admin_store: MagicMock, header: str | None) -> None:
    """Missing, wrong, or non bearer credentials are rejected."""
    headers = {"Authorization": header} if header else {}
    response = TestClient(api.app).get("/api/admin/metrics", headers=headers)
    assert response.status_code == 401
    admin_store.metrics.assert_not_called()


def test_admin_metrics_returns_store_metrics_for_range(admin_store: MagicMock) -> None:
    """A valid token returns the store's metrics for the range, granularity, 5 s target, and $50 budget."""
    response = TestClient(api.app).get(
        "/api/admin/metrics", params={"range": "90d", "bucket": "week"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"calls": 3}
    assert response.json()["budget"]["recipients"] == "weather@wsu.edu"
    admin_store.metrics.assert_called_once_with(
        90, "America/Los_Angeles", bucket="week", target_ms=5000, budget_usd=50.0
    )


def test_admin_metrics_csv_exports_the_time_series(admin_store: MagicMock) -> None:
    """The overview export has one row per day, week, or month."""
    admin_store.metrics.return_value = {
        "range": {"bucket": "day"},
        "series": [{"bucket": "2026-10-14", "calls": 4, "users": 2}, {"bucket": "2026-10-15", "calls": 1, "users": 1}],
        "budget": {},
    }
    response = TestClient(api.app).get("/api/admin/metrics.csv", headers={"Authorization": "Bearer s3cret"})

    assert response.status_code == 200
    assert "awn-llm-usage-30d-by-day.csv" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("bucket,calls,unidentified_calls")
    assert [line.split(",")[:2] for line in lines[1:]] == [["2026-10-14", "4"], ["2026-10-15", "1"]]


def test_admin_metrics_rejects_unknown_granularity(admin_store: MagicMock) -> None:
    """Only day, week, and month grouping is accepted."""
    response = TestClient(api.app).get(
        "/api/admin/metrics", params={"bucket": "year"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 422


def test_admin_metrics_rejects_unknown_range(admin_store: MagicMock) -> None:
    """Only the dashboard's preset ranges are accepted."""
    response = TestClient(api.app).get(
        "/api/admin/metrics", params={"range": "5y"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 422


def test_admin_users_returns_a_page_of_per_user_costs(admin_store: MagicMock) -> None:
    """The per user endpoint passes range and paging through to the store."""
    admin_store.users.return_value = {"users": [], "total_users": 0}
    response = TestClient(api.app).get(
        "/api/admin/users",
        params={"range": "7d", "limit": 25, "offset": 50},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert response.status_code == 200
    admin_store.users.assert_called_once_with(
        7, "America/Los_Angeles", limit=25, offset=50, search=None, sort="cost_usd", descending=True
    )


def test_admin_users_passes_search_and_sort(admin_store: MagicMock) -> None:
    """Search text and the clicked column and direction reach the store."""
    admin_store.users.return_value = {"users": []}
    response = TestClient(api.app).get(
        "/api/admin/users",
        params={"search": "browser-1", "sort": "last_seen", "order": "asc"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert response.status_code == 200
    _, kwargs = admin_store.users.call_args
    assert (kwargs["search"], kwargs["sort"], kwargs["descending"]) == ("browser-1", "last_seen", False)


@pytest.mark.parametrize("params", [{"sort": "user_id; DROP TABLE x"}, {"order": "sideways"}, {"search": "x" * 65}])
def test_admin_users_rejects_invalid_search_and_sort(admin_store: MagicMock, params: dict) -> None:
    """Unknown sort columns, directions, and overlong searches are rejected before reaching the database."""
    response = TestClient(api.app).get("/api/admin/users", params=params, headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 422
    admin_store.users.assert_not_called()


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/users.csv"])
def test_admin_user_endpoints_require_the_token(admin_store: MagicMock, path: str) -> None:
    """Per user costs are admin only."""
    assert TestClient(api.app).get(path).status_code == 401
    admin_store.users.assert_not_called()


def test_admin_users_csv_lists_every_user_and_the_unidentified_total(admin_store: MagicMock) -> None:
    """The CSV export has one row per user plus an unidentified row."""
    row = {"requests": 3, "sessions": 2, "llm_calls": 12, "input_tokens": 9, "output_tokens": 4, "cost_usd": 0.5}
    admin_store.users.return_value = {
        "users": [{**row, "user_id": "browser-1", "cost_share": 0.8}],
        "unidentified": {**row, "user_id": None, "cost_share": 0.2},
    }
    response = TestClient(api.app).get("/api/admin/users.csv", headers={"Authorization": "Bearer s3cret"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "awn-llm-cost-by-user-30d.csv" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("user_id,requests,sessions,llm_calls")
    assert [line.split(",")[0] for line in lines[1:]] == ["browser-1", "(unidentified)"]


def test_admin_users_csv_neutralizes_formula_user_ids(admin_store: MagicMock) -> None:
    """A user id such as -1-2 is written as text so spreadsheets do not run it as a formula."""
    row = {"requests": 1, "sessions": 1, "llm_calls": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.1}
    admin_store.users.return_value = {
        "users": [{**row, "user_id": "-1-2"}, {**row, "user_id": "=cmd"}, {**row, "user_id": "j.doe@wsu.edu"}],
        "unidentified": None,
    }
    response = TestClient(api.app).get("/api/admin/users.csv", headers={"Authorization": "Bearer s3cret"})
    assert [line.split(",")[0] for line in response.text.strip().splitlines()[1:]] == [
        "'-1-2",
        "'=cmd",
        "j.doe@wsu.edu",
    ]


def test_admin_users_csv_follows_the_table_search(admin_store: MagicMock) -> None:
    """A searched export lists only the matches and leaves out the unidentified row."""
    row = {"requests": 1, "sessions": 1, "llm_calls": 4, "input_tokens": 9, "output_tokens": 4, "cost_usd": 0.1}
    admin_store.users.return_value = {
        "users": [{**row, "user_id": "browser-1"}],
        "unidentified": {**row, "user_id": None},
    }
    response = TestClient(api.app).get(
        "/api/admin/users.csv", params={"search": "browser"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert [line.split(",")[0] for line in response.text.strip().splitlines()[1:]] == ["browser-1"]
    assert admin_store.users.call_args.kwargs["search"] == "browser"
