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

    call_cost = 1_000 * 0.02 / 1e6 + (1_000 * 1.0 + 250 * 4.0) / 1e6
    assert (summary["calls"], summary["unidentified_calls"], summary["failed_calls"]) == (5, 1, 1)
    assert summary["error_rate"] == pytest.approx(0.2)
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
    # answered calls took 500, 1000, 2000, 3000 ms; three are within the 2.5 s target
    assert summary["latency_p50_ms"] == pytest.approx(1_500)
    assert summary["within_target_rate"] == pytest.approx(0.75)
    assert metrics["previous"]["calls"] == 0
    assert metrics["target_ms"] == 2_500

    assert len(metrics["series"]) == 7
    assert (metrics["series"][-1]["bucket"], metrics["series"][-1]["calls"]) == ("2026-10-15", 2)
    assert {row["status"]: row["requests"] for row in metrics["by_status"]} == {"ok": 3, "error": 1, "empty": 1}
    assert {(row["model"], row["priced"]) for row in metrics["by_model"]} == {("paid/chat", True), ("paid/embed", True)}
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
    with store._connect() as conn:
        conn.execute("UPDATE usage_budget_alerts SET attempted_at = now() - interval '2 hours'")
    assert store.claim_budget_alert(month, 50.0, 53.0, "weather@wsu.edu")  # retry allowed

    store.finish_budget_alert(month, 50.0, delivered=True, error=None)
    with store._connect() as conn:
        conn.execute("UPDATE usage_budget_alerts SET attempted_at = now() - interval '2 hours'")
    assert not store.claim_budget_alert(month, 50.0, 60.0, "weather@wsu.edu")  # delivered: never again


def test_month_spend_ignores_demo_data(store: UsageStore) -> None:
    """Demo rows never count toward the real monthly budget."""
    store.record(_request("u1", "s1", 1, "ok", 100))
    with store._connect() as conn:
        conn.execute("UPDATE usage_requests SET is_demo = true")
    assert store.month_spend(_TZ, now=_NOW)[1] == 0.0


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
    assert result["metrics"]["summary"]["calls"] == 1


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
