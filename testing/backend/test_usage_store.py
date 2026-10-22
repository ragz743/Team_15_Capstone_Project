"""Integration tests for UsageStore against a real Postgres (skipped when none is reachable).

Uses the same PG_HOST / PG_PORT / PG_USER / PG_PASSWORD settings as the rest of the backend,
and works in a throwaway schema so it never touches real usage data.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dotenv
import psycopg
import pytest
from backend.analytics.metering import LlmCall, RequestStatus, RequestUsage
from backend.analytics.pricing import ModelPrice, PriceTable
from backend.analytics.usage_store import UsageStore
from psycopg import sql

_TZ = "America/Los_Angeles"
# fixed "now" so day and month buckets are deterministic
_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo(_TZ))


def _conn_info() -> dict:
    dotenv.load_dotenv()
    info = {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": "vectorstore",
    }
    for key, env in (("user", "PG_USER"), ("password", "PG_PASSWORD")):
        if os.getenv(env):
            info[key] = os.getenv(env)
    return info


@pytest.fixture
def store():
    """Yield a UsageStore writing into a temporary schema that is dropped afterwards."""
    info = _conn_info()
    try:
        admin = psycopg.connect(**info, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable")

    schema = f"usage_test_{uuid.uuid4().hex[:8]}"
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    prices = PriceTable({"paid/chat": ModelPrice(1.0, 4.0), "paid/embed": ModelPrice(0.02, 0)})
    store = UsageStore(lambda: psycopg.connect(**info, options=f"-c search_path={schema}"), prices)
    try:
        yield store
    finally:
        store.close()
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def _request(
    user: str | None, session: str | None, days_ago: float, status: RequestStatus, latency: int
) -> RequestUsage:
    started = _NOW - timedelta(days=days_ago, minutes=1)
    usage = RequestUsage(user_id=user, session_id=session, started_at=started, latency_ms=latency, status=status)
    usage.calls = [
        LlmCall(kind="embedding", model="paid/embed", called_at=started, input_tokens=1_000, tokens_estimated=True),
        LlmCall(kind="chat", model="paid/chat", called_at=started, input_tokens=1_000, output_tokens=250),
    ]
    return usage


def test_metrics_aggregate_cost_users_sessions_and_latency(store: UsageStore) -> None:
    """KPIs combine requests and calls in the window and ignore older requests."""
    for usage in [
        _request("u1", "s1", 0, "ok", 1_000),
        _request("u1", "s1", 0, "ok", 3_000),
        _request("u1", "s2", 1, "error", 200),
        _request("u2", "s3", 2, "ok", 2_000),
        _request(None, None, 3, "empty", 500),
        _request("u3", "s4", 40, "ok", 9_000),  # older than both the window and the previous period
    ]:
        store.record(usage)

    metrics = store.metrics(7, _TZ, now=_NOW)
    summary = metrics["summary"]

    call_cost = 1_000 * 0.02 / 1e6 + (1_000 * 1.0 + 250 * 4.0) / 1e6
    assert summary["requests"] == 5
    assert summary["llm_calls"] == 10
    assert (summary["chat_calls"], summary["embedding_calls"]) == (5, 5)
    assert summary["cost_usd"] == pytest.approx(5 * call_cost)
    assert summary["avg_cost_per_call"] == pytest.approx(call_cost / 2)
    assert (summary["users"], summary["sessions"]) == (2, 3)
    assert summary["avg_sessions_per_user"] == pytest.approx(1.5)
    # cost per user only counts requests from identified users
    assert summary["avg_cost_per_user"] == pytest.approx(4 * call_cost / 2)
    assert summary["unidentified_requests"] == 1
    assert summary["error_rate"] == pytest.approx(0.2)
    # response time only covers answered requests: 500, 1000, 2000, 3000
    assert summary["latency_p50_ms"] == pytest.approx(1_500)
    assert metrics["previous"]["requests"] == 0  # the 40 day old request is outside both windows

    assert len(metrics["series"]) == 7
    assert metrics["series"][-1]["bucket"] == "2026-10-15"
    assert metrics["series"][-1]["requests"] == 2
    assert {row["status"]: row["requests"] for row in metrics["by_status"]} == {"ok": 3, "error": 1, "empty": 1}
    assert {(row["model"], row["priced"]) for row in metrics["by_model"]} == {("paid/chat", True), ("paid/embed", True)}
    assert not metrics["includes_demo_data"]


def test_metrics_months_cover_whole_calendar_months(store: UsageStore) -> None:
    """Monthly buckets start at the first of the month and flag the current month as partial."""
    store.record(_request("u1", "s1", 20, "ok", 1_000))  # 2026-09-25
    store.record(_request("u2", "s2", 1, "ok", 1_000))  # 2026-10-14

    months = store.metrics(30, _TZ, now=_NOW)["months"]

    assert [(m["bucket"], m["users"], m["partial"]) for m in months] == [
        ("2026-09-01", 1, False),
        ("2026-10-01", 1, True),
    ]


def test_unpriced_models_are_recorded_at_zero_and_flagged(store: UsageStore) -> None:
    """Models missing from the price table cost nothing and report priced=False."""
    usage = _request("u1", "s1", 0, "ok", 100)
    usage.calls = [LlmCall(kind="chat", model="unknown/model", called_at=usage.started_at, input_tokens=10)]
    store.record(usage)

    [row] = store.metrics(7, _TZ, now=_NOW)["by_model"]
    assert (row["model"], row["cost_usd"], row["priced"]) == ("unknown/model", 0.0, False)


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
    assert result["metrics"]["summary"]["requests"] == 1


def test_cost_source_distinguishes_billed_and_estimated_costs(store: UsageStore) -> None:
    """Models whose cost the provider reported are labelled billed; pricing.yaml ones estimated."""
    usage = _request("u1", "s1", 0, "ok", 100)
    usage.calls = [
        LlmCall(kind="chat", model="billed/model", called_at=usage.started_at, input_tokens=10, cost_usd=0.25),
        LlmCall(kind="chat", model="paid/chat", called_at=usage.started_at, input_tokens=1_000_000),
    ]
    store.record(usage)

    rows = {row["model"]: row for row in store.metrics(7, _TZ, now=_NOW)["by_model"]}
    assert (rows["billed/model"]["cost_source"], rows["billed/model"]["cost_usd"]) == ("billed", 0.25)
    assert (rows["paid/chat"]["cost_source"], rows["paid/chat"]["cost_usd"]) == ("estimated", 1.0)


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
    call_cost = 1_000 * 0.02 / 1e6 + (1_000 * 1.0 + 250 * 4.0) / 1e6

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
