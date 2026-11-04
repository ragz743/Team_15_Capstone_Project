"""Integration tests for UsageStore against a real MariaDB/MySQL (skipped when none is reachable).

Never point these at AgWeatherNet's server: each test creates its own throwaway database with schema.sql
and drops it afterwards. Start a local server with

    docker run -d --rm --name awn-usage-test -e MARIADB_ROOT_PASSWORD=usage-test -p 127.0.0.1:3308:3306 mariadb:10.11

and run with AWN_USAGE_TEST_DB_PORT=3308 AWN_USAGE_TEST_DB_PASSWORD=usage-test (host 127.0.0.1 and user root
by default; also AWN_USAGE_TEST_DB_HOST / AWN_USAGE_TEST_DB_USER).
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import backend.api as api
import mysql.connector
import pytest
from backend.analytics import admin_api
from backend.analytics.metering import LlmCall, RequestStatus, RequestUsage
from backend.analytics.usage_store import UsageDatabaseConfig, UsageStore, UsageTracker
from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_store import ConversationStore
from backend.workflow.contracts import WorkflowRequest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

_TZ = "America/Los_Angeles"
# fixed "now" so day and month buckets are deterministic
_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo(_TZ))


_SCHEMA = Path(__file__).resolve().parents[2] / "code_/backend/analytics/schema.sql"


def _execute(store: UsageStore, statement: str, params: tuple = ()) -> list[tuple]:
    """Run one statement on the store's test database, as a test setting up or checking rows directly."""
    with closing(store._connect()) as conn, closing(conn.cursor()) as cur:
        cur.execute(statement, params)
        return cur.fetchall() if cur.with_rows else []


@pytest.fixture
def store():
    """Yield a UsageStore writing into a temporary database (the client's tables) that is dropped afterwards."""
    base = UsageDatabaseConfig(
        user=os.getenv("AWN_USAGE_TEST_DB_USER", "root"),
        password=os.getenv("AWN_USAGE_TEST_DB_PASSWORD", ""),
        host=os.getenv("AWN_USAGE_TEST_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("AWN_USAGE_TEST_DB_PORT") or 3306),
        database="",
    )
    try:
        admin = mysql.connector.connect(
            user=base.user,
            password=base.password,
            host=base.host,
            port=base.port,
            connection_timeout=2,
            autocommit=True,
        )
    except mysql.connector.Error:
        pytest.skip("No MariaDB/MySQL test server is reachable (see this module's docstring)")

    database = f"usage_test_{uuid.uuid4().hex[:8]}"
    with closing(admin.cursor()) as cur:
        cur.execute(f"CREATE DATABASE {database}")
        cur.execute(f"USE {database}")
        # schema.sql names the awn database; create the same tables in the throwaway one
        # comments contain semicolons, so drop them before splitting into statements
        ddl = re.sub(r"--[^\n]*", "", _SCHEMA.read_text(encoding="utf-8")).replace("awn.", "")
        for statement in ddl.split(";"):
            if "CREATE TABLE" in statement:
                cur.execute(statement)
    config = UsageDatabaseConfig(base.user, base.password, base.host, base.port, database)
    store = UsageStore(config.connect)
    try:
        yield store
    finally:
        store.close()
        with closing(admin.cursor()) as cur:
            cur.execute(f"DROP DATABASE {database}")
        admin.close()


def _request(
    user: str | None, session: str | None, days_ago: float, status: RequestStatus, latency: int
) -> RequestUsage:
    started = _NOW - timedelta(days=days_ago, minutes=1)
    usage = RequestUsage(user_id=user, session_id=session, started_at=started, latency_ms=latency, status=status)
    usage.calls = [
        # costs as OpenRouter reports them
        LlmCall(model="paid/sql", called_at=started, input_tokens=1_000, tokens_estimated=True, cost_usd=0.00002),
        LlmCall(model="paid/chat", called_at=started, input_tokens=1_000, output_tokens=250, cost_usd=0.002),
    ]
    return usage


def test_saved_chat_usage_reaches_dashboard_and_csv_without_counting_replays(store, database, monkeypatch):
    """HTTP, saved turns (Postgres), model callbacks and admin reads (MariaDB) use real isolated storage."""
    monkeypatch.setattr(api, "_conversations", ConversationStore(database))
    monkeypatch.setattr(api, "_usage_tracker", UsageTracker(store))
    monkeypatch.setattr(admin_api, "_usage_store", store)
    monkeypatch.setenv("AWN_ADMIN_TOKEN", "local-test")
    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="72 F",
                    usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                    response_metadata={"model_name": "paid/chat", "cost": 0.002},
                )
                for _ in range(3)
            ]
        )
    )
    weather = MagicMock()
    weather.prepare_turn.side_effect = lambda question, context, **_: PreparedChatTurn(
        question=question,
        context=context.model_copy(update={"station_ids": ["1"]}),
        outcome="weather",
        workflow=WorkflowRequest(station_id="1", reference_time=datetime.now(UTC)),
    )
    calls = 0

    def answer(turn):
        nonlocal calls
        calls += 1
        reply = str(model.invoke([turn.question]).content)
        if calls == 2:
            raise RuntimeError("failure after a billed model call")
        return AnsweredTurn(reply=reply, outcome="success")

    weather.answer_result.side_effect = answer
    monkeypatch.setattr(api, "_retriever", weather)
    client = TestClient(api.app)
    conversation = client.post("/api/conversations").json()["id"]
    headers = {"X-AWN-User-Id": "sai@wsu.edu", "X-AWN-Session-Id": "login-1"}
    payload = {"conversation_id": conversation, "request_id": str(uuid.uuid4()), "message": "Temperature?"}
    response = client.post("/api/chat", json=payload, headers=headers)
    assert response.status_code == 200
    assert client.post("/api/chat", json=payload, headers=headers).json() == response.json()
    payload["request_id"] = str(uuid.uuid4())
    assert client.post("/api/chat", json=payload, headers=headers).status_code == 502
    assert client.post("/api/chat", json=payload, headers=headers).status_code == 200

    admin = {"Authorization": "Bearer local-test"}
    metrics = client.get("/api/admin/metrics", headers=admin)
    assert metrics.status_code == 200
    summary = metrics.json()["summary"]
    assert (summary["calls"], summary["model_requests"], summary["failed_calls"]) == (3, 3, 1)
    assert (summary["users"], summary["sessions"], summary["successful_sessions"]) == (1, 1, 0)
    assert summary["cost_usd"] == pytest.approx(0.006)
    assert metrics.json()["includes_demo_data"] is False
    users = client.get("/api/admin/users", headers=admin).json()["users"]
    assert len(users) == 1 and users[0]["user_id"] == "sai@wsu.edu"
    assert users[0]["cost_usd"] == pytest.approx(0.006)
    export = client.get("/api/admin/users.csv", headers=admin)
    assert export.status_code == 200 and "sai@wsu.edu" in export.text
    assert _execute(store, "SELECT count(*) FROM table_llm_usage_model_calls WHERE cost_reported = 1") == [(3,)]
    # the client's table also has kind and priced; the chatbot only makes chat requests
    assert _execute(store, "SELECT DISTINCT kind, priced FROM table_llm_usage_model_calls") == [("chat", 1)]


def test_metrics_aggregate_calls_users_sessions_and_latency(store: UsageStore) -> None:
    """KPIs follow the client's definitions: calls, logged-in users, guests, login sessions, 5 second target."""
    for usage in [
        _request("u1", "s1", 0, "ok", 1_000),
        _request("u1", "s1", 0, "ok", 3_000),
        _request("u1", "s2", 1, "error", 200),
        _request("u2", "s3", 2, "ok", 2_000),
        _request(None, None, 3, "empty", 500),  # a guest (not logged in)
        _request("u3", "s4", 40, "ok", 9_000),  # older than both the window and the previous period
    ]:
        store.record(usage)

    metrics = store.metrics(7, _TZ, target_ms=2_500, now=_NOW)
    summary = metrics["summary"]

    call_cost = 0.00002 + 0.002  # the two model requests in _request
    assert (summary["calls"], summary["unidentified_calls"], summary["failed_calls"]) == (5, 1, 2)
    assert summary["error_rate"] == pytest.approx(0.4)
    assert summary["model_requests"] == 10
    assert summary["cost_usd"] == pytest.approx(5 * call_cost)
    assert summary["avg_cost_per_call"] == pytest.approx(call_cost)  # one call = one end to end question
    assert summary["cost_per_1000_calls"] == pytest.approx(1_000 * call_cost)
    assert summary["users"] == 2  # logged-in users only; the guest is not a user
    assert summary["avg_cost_per_user"] == pytest.approx(4 * call_cost / 2)
    # login sessions: s1 (all answered), s2 (an error), s3 (all answered)
    assert (summary["sessions"], summary["successful_sessions"]) == (3, 2)
    assert summary["successful_session_rate"] == pytest.approx(2 / 3)
    assert summary["avg_sessions_per_user"] == pytest.approx(1.5)
    # Empty replies are HTTP 502 failures, not fast answers. Two of three answers meet the target.
    assert summary["latency_p50_ms"] == pytest.approx(2_000)
    assert summary["within_target_rate"] == pytest.approx(2 / 3)
    assert metrics["previous"]["calls"] == 0
    assert metrics["target_ms"] == 2_500

    assert len(metrics["series"]) == 7
    assert sum(point["failed_calls"] for point in metrics["series"]) == 2
    assert (metrics["series"][-1]["bucket"], metrics["series"][-1]["calls"]) == ("2026-10-15", 2)
    assert {row["status"]: row["requests"] for row in metrics["by_status"]} == {"ok": 3, "error": 1, "empty": 1}
    assert {(row["model"], row["cost_source"]) for row in metrics["by_model"]} == {
        ("paid/chat", "billed"),
        ("paid/sql", "billed"),
    }
    assert not metrics["includes_demo_data"]
    assert metrics["quality"] == {"runs": [], "latest": None}
    assert metrics["budget"]["spent_usd"] == pytest.approx(5 * call_cost)  # October so far


@pytest.mark.parametrize(("bucket", "expected"), [("week", 5), ("month", 2)])
def test_metrics_series_granularity(store: UsageStore, bucket: str, expected: int) -> None:
    """The time series can be grouped by day, week, or month."""
    store.record(_request("u1", "s1", 20, "ok", 1_000))  # 2026-09-25
    store.record(_request("u2", "s2", 1, "ok", 1_000))  # 2026-10-14

    series = store.metrics(30, _TZ, bucket=bucket, now=_NOW)["series"]  # type: ignore[arg-type]

    assert len(series) == expected
    assert sum(point["calls"] for point in series) == 2
    if bucket == "month":
        assert [(p["bucket"], p["users"]) for p in series] == [("2026-09-01", 1), ("2026-10-01", 1)]


def test_quality_runs_appear_in_metrics(store: UsageStore) -> None:
    """Saved retrieval quality runs are listed, with the latest run's question by question details."""
    details = [{"question": "q", "source": "current", "expected": "Pullman", "passed": True, "found": ["Pullman"]}]
    store.record_quality_run(samples=4, passed=3, details=details)

    quality = store.metrics(7, _TZ)["quality"]

    assert [(run["samples"], run["passed"], run["score"]) for run in quality["runs"]] == [(4, 3, 0.75)]
    assert quality["latest"]["details"] == details
    assert store.latest_quality_run_at() is not None


def test_budget_alert_is_claimed_once_per_month(store: UsageStore) -> None:
    """Only one caller wins the month's alert; a failed send can be retried after about an hour."""
    month = _NOW.date().replace(day=1)
    assert store.claim_budget_alert(month, 50.0, 51.0, "weather@wsu.edu")
    assert not store.claim_budget_alert(month, 50.0, 52.0, "weather@wsu.edu")  # already claimed

    store.finish_budget_alert(month, 50.0, delivered=False, error="SMTP down")
    assert not store.claim_budget_alert(month, 50.0, 52.0, "weather@wsu.edu")  # too soon to retry
    _execute(store, "UPDATE table_llm_usage_budget_alerts SET attempted_at = UTC_TIMESTAMP() - INTERVAL 2 HOUR")
    assert store.claim_budget_alert(month, 50.0, 53.0, "weather@wsu.edu")  # retry allowed

    store.finish_budget_alert(month, 50.0, delivered=True, error=None)
    _execute(store, "UPDATE table_llm_usage_budget_alerts SET attempted_at = UTC_TIMESTAMP() - INTERVAL 2 HOUR")
    assert not store.claim_budget_alert(month, 50.0, 60.0, "weather@wsu.edu")  # delivered: never again
    alert = store.budget_status(_TZ, 50.0, now=_NOW)["alert"]
    assert alert is not None and alert["delivered"] is True


def test_month_spend_ignores_demo_data(store: UsageStore) -> None:
    """Demo rows never count toward the real monthly budget."""
    store.record(_request("u1", "s1", 1, "ok", 100))
    _execute(store, "UPDATE table_llm_usage_requests SET is_demo = 1")
    assert store.month_spend(_TZ, now=_NOW)[1] == 0.0


def test_quality_checks_are_not_user_requests(store: UsageStore) -> None:
    """A quality check is stored on its own; it adds no calls, and (no cost column) no spending."""
    store.record(_request("u1", "s1", 1, "ok", 100))
    before = store.month_spend(_TZ, now=_NOW)[1]
    call = LlmCall(model="paid/chat", called_at=_NOW, input_tokens=1_000, output_tokens=250, cost_usd=0.002)
    store.record_quality_run(samples=1, passed=1, details=[], calls=[call])
    assert store.month_spend(_TZ, now=_NOW)[1] == pytest.approx(before)
    assert store.metrics(7, _TZ, now=_NOW)["summary"]["calls"] == 1  # still one user request


def test_month_spend_uses_the_dashboard_timezone(store: UsageStore) -> None:
    """Timestamps are stored in UTC; a call on Sep 30 at 11 pm Pacific (Oct 1 UTC) is September spending."""
    usage = _request("u1", "s1", 0, "ok", 100)
    usage.started_at = datetime(2026, 9, 30, 23, 0, tzinfo=ZoneInfo(_TZ))
    store.record(usage)
    assert store.month_spend(_TZ, now=_NOW)[1] == 0.0
    assert store.month_spend(_TZ, now=datetime(2026, 9, 30, 23, 30, tzinfo=ZoneInfo(_TZ)))[1] > 0
    stored = _execute(store, "SELECT started_at FROM table_llm_usage_requests")[0][0]
    assert stored == datetime(2026, 10, 1, 6, 0)  # naive UTC, as the client's DATETIME(3) columns expect


def test_long_values_are_trimmed_to_the_client_columns(store: UsageStore) -> None:
    """The server runs in strict mode, so text longer than a column would otherwise lose the whole call."""
    usage = _request("u1", "s1", 0, "error", 100)
    usage.error_type = "E" * 300
    usage.calls[0].model = "m" * 300
    store.record(usage)
    assert store.metrics(7, _TZ, now=_NOW)["summary"]["calls"] == 1


def test_calls_without_a_reported_cost_are_recorded_at_zero_and_flagged(store: UsageStore) -> None:
    """A model whose provider reported no cost counts as $0 and is labelled unreported."""
    usage = _request("u1", "s1", 0, "ok", 100)
    usage.calls = [LlmCall(model="local/model", called_at=usage.started_at, input_tokens=10)]
    store.record(usage)

    [row] = store.metrics(7, _TZ, now=_NOW)["by_model"]
    assert (row["model"], row["cost_usd"], row["cost_source"]) == ("local/model", 0.0, "unreported")


def test_dashboard_reads_do_not_wait_for_the_write_connection(store: UsageStore) -> None:
    """Metrics use their own connection, so a busy write lock never delays the dashboard (or vice versa)."""
    store.record(_request("u1", "s1", 0, "ok", 1_000))
    result: dict = {}

    def read() -> None:
        result["metrics"] = store.metrics(7, _TZ, now=_NOW)

    with store._lock:  # simulate a chat request holding the write connection
        reader = threading.Thread(target=read)
        reader.start()
        reader.join(timeout=10)

    assert not reader.is_alive(), "metrics waited on the write lock"
    assert result["metrics"]["summary"]["calls"] == 1


def test_cost_source_shows_whether_every_cost_was_reported(store: UsageStore) -> None:
    """A model is billed when every request reported a cost, mixed when only some did."""
    usage = _request("u1", "s1", 0, "ok", 100)
    usage.calls = [
        LlmCall(model="billed/model", called_at=usage.started_at, input_tokens=10, cost_usd=0.25),
        LlmCall(model="mixed/model", called_at=usage.started_at, cost_usd=0.5),
        LlmCall(model="mixed/model", called_at=usage.started_at),
    ]
    store.record(usage)

    rows = {row["model"]: row for row in store.metrics(7, _TZ, now=_NOW)["by_model"]}
    assert (rows["billed/model"]["cost_source"], rows["billed/model"]["cost_usd"]) == ("billed", 0.25)
    assert (rows["mixed/model"]["cost_source"], rows["mixed/model"]["cost_usd"]) == ("mixed", 0.5)


def test_users_break_down_cost_per_user_most_expensive_first(store: UsageStore) -> None:
    """Each user's questions, sessions, calls, tokens, and cost add up, sorted by cost with paging."""
    for usage in [
        _request("heavy", "s1", 0, "ok", 100),
        _request("heavy", "s2", 1, "ok", 100),
        _request("heavy", "s2", 1, "error", 100),
        _request("light", "s3", 2, "ok", 100),
        _request(None, None, 2, "ok", 100),
        _request("old", "s4", 40, "ok", 100),  # outside the 7 day window
    ]:
        store.record(usage)
    call_cost = 0.00002 + 0.002  # the two model requests in _request

    result = store.users(7, _TZ, now=_NOW)

    assert (result["total_users"], [u["user_id"] for u in result["users"]]) == (2, ["heavy", "light"])
    heavy = result["users"][0]
    assert (heavy["requests"], heavy["sessions"], heavy["llm_calls"]) == (3, 2, 6)
    assert (heavy["input_tokens"], heavy["output_tokens"]) == (6_000, 750)
    assert heavy["cost_usd"] == pytest.approx(3 * call_cost)
    assert heavy["cost_share"] == pytest.approx(3 / 5)
    assert heavy["avg_cost_per_request"] == pytest.approx(call_cost)
    assert result["total_cost_usd"] == pytest.approx(5 * call_cost)
    # requests without a user id are reported separately, not as a user
    assert (result["unidentified"]["requests"], result["unidentified"]["cost_share"]) == (1, pytest.approx(1 / 5))
    # 2 users: the top 10% rounds up to the single most expensive user
    assert result["top_decile_cost_share"] == pytest.approx(3 / 4)

    second_page = store.users(7, _TZ, limit=1, offset=1, now=_NOW)
    assert [u["user_id"] for u in second_page["users"]] == ["light"]


def test_users_without_any_traffic(store: UsageStore) -> None:
    """An empty window returns no users and no unidentified group."""
    result = store.users(7, _TZ, now=_NOW)
    assert (result["total_users"], result["users"], result["unidentified"]) == (0, [], None)
    assert result["top_decile_cost_share"] is None


def _seed_users(store: UsageStore) -> None:
    """Three identified users with different activity, plus one unidentified question."""
    for usage in [
        _request("alice", "a1", 0, "ok", 100),
        _request("alice", "a2", 1, "ok", 100),
        _request("alice", "a2", 1, "ok", 100),
        _request("bob_smith", "b1", 2, "ok", 100),
        _request("carol%x", "c1", 0.5, "ok", 100),
        _request("carol%x", "c1", 0.6, "ok", 100),
        _request(None, None, 1, "ok", 100),
    ]:
        store.record(usage)


@pytest.mark.parametrize(
    ("sort", "descending", "expected"),
    [
        ("cost_usd", True, ["alice", "carol%x", "bob_smith"]),
        ("cost_usd", False, ["bob_smith", "carol%x", "alice"]),
        ("requests", True, ["alice", "carol%x", "bob_smith"]),
        ("sessions", True, ["alice", "bob_smith", "carol%x"]),  # ties break on user id
        ("user_id", False, ["alice", "bob_smith", "carol%x"]),
        ("user_id", True, ["carol%x", "bob_smith", "alice"]),
        ("last_seen", True, ["alice", "carol%x", "bob_smith"]),
        ("total_tokens", False, ["bob_smith", "carol%x", "alice"]),
    ],
)
def test_users_sort_by_any_column(store: UsageStore, sort, descending: bool, expected: list[str]) -> None:
    """Every sortable column orders users in both directions."""
    _seed_users(store)
    result = store.users(7, _TZ, sort=sort, descending=descending, now=_NOW)
    assert [u["user_id"] for u in result["users"]] == expected
    assert (result["sort"], result["order"]) == (sort, "desc" if descending else "asc")


def test_users_search_matches_part_of_the_id_case_insensitively(store: UsageStore) -> None:
    """Search keeps users whose id contains the text; totals still describe everyone."""
    _seed_users(store)
    result = store.users(7, _TZ, search="SMI", now=_NOW)

    assert [u["user_id"] for u in result["users"]] == ["bob_smith"]
    assert (result["matched_users"], result["total_users"], result["search"]) == (1, 3, "SMI")
    # share of cost stays relative to everyone's cost, not just the matches
    assert result["users"][0]["cost_share"] == pytest.approx(1 / 7)


@pytest.mark.parametrize(("search", "expected"), [("%", ["carol%x"]), ("_", ["bob_smith"]), ("nobody", [])])
def test_users_search_treats_wildcards_literally(store: UsageStore, search: str, expected: list[str]) -> None:
    """% and _ in a search match those characters, not 'anything'."""
    _seed_users(store)
    assert [u["user_id"] for u in store.users(7, _TZ, search=search, now=_NOW)["users"]] == expected


def test_users_reject_unknown_sort_columns(store: UsageStore) -> None:
    """Only allowlisted columns can be sorted on, so nothing user supplied reaches ORDER BY."""
    with pytest.raises(ValueError, match="unsupported sort column"):
        store.users(7, _TZ, sort="cost_usd; DROP TABLE usage_requests", now=_NOW)  # type: ignore[arg-type]
