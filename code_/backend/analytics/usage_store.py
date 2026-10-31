"""Persist request usage and compute the admin dashboard metrics."""

from __future__ import annotations

import logging
import pathlib
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import psycopg
from backend.analytics.metering import RequestUsage, metered
from backend.analytics.pricing import PriceTable
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

logger = logging.getLogger("awn.analytics")

_SCHEMA_FILE = pathlib.Path(__file__).with_name("schema.sql")

# after the database is unreachable, skip recording for this long instead of making every chat request wait
_RETRY_AFTER_SECONDS = 30


class UsageStoreUnavailableError(RuntimeError):
    """Raised instead of writing while the database recently failed to connect."""


Bucket = Literal["day", "week", "month"]

# Requests that produced an answer count toward response time; the rest count as failures.
_ANSWERED = ("ok",)
_FAILED = ("empty", "error", "rate_limited", "unavailable")

# Shared CTEs:
#   r: the calls (end to end questions, one usage_requests row each) in the window
#   c: the model requests (chat and embedding) made while answering those calls; attributed to their
#      call's start time so cost and call counts always agree
#   s: the login sessions with calls in the window; a session is successful when every call was answered
_WINDOW = """
    WITH r AS (
        SELECT * FROM usage_requests WHERE started_at >= %(start)s AND started_at < %(end)s
    ),
    c AS (
        SELECT usage_llm_calls.*, r.user_id, r.started_at AS request_started_at
        FROM usage_llm_calls JOIN r USING (request_id)
    ),
    s AS (
        SELECT session_id, min(started_at) AS started_at, bool_and(status = 'ok') AS successful
        FROM r WHERE session_id IS NOT NULL GROUP BY session_id
    )
"""

_SUMMARY_SQL = (
    _WINDOW
    + """
    SELECT
        (SELECT count(*) FROM r) AS requests,
        (SELECT count(*) FROM r WHERE user_id IS NULL) AS unidentified_requests,
        (SELECT count(*) FROM r WHERE status = ANY(%(failed)s)) AS failed_requests,
        (SELECT count(DISTINCT user_id) FROM r) AS users,
        (SELECT count(*) FROM s) AS sessions,
        (SELECT count(*) FROM s WHERE successful) AS successful_sessions,
        (SELECT count(*) FROM r WHERE status = ANY(%(answered)s)) AS answered_requests,
        (SELECT count(*) FROM r WHERE status = ANY(%(answered)s) AND latency_ms <= %(target_ms)s) AS within_target,
        (SELECT count(DISTINCT (user_id, session_id)) FROM r
            WHERE user_id IS NOT NULL AND session_id IS NOT NULL) AS user_sessions,
        (SELECT count(*) FROM r WHERE session_id IS NOT NULL) AS session_requests,
        (SELECT count(*) FROM c WHERE kind = 'chat') AS chat_calls,
        (SELECT count(*) FROM c WHERE kind = 'embedding') AS embedding_calls,
        (SELECT coalesce(sum(cost_usd), 0) FROM c) AS cost_usd,
        (SELECT coalesce(sum(cost_usd), 0) FROM c WHERE user_id IS NOT NULL) AS identified_cost_usd,
        (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FROM r
            WHERE status = ANY(%(answered)s)) AS latency_p50_ms,
        (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM r
            WHERE status = ANY(%(answered)s)) AS latency_p95_ms,
        (SELECT coalesce(bool_or(is_demo), false) FROM r) AS includes_demo_data
"""
)

_SERIES_SQL = (
    _WINDOW
    + """
    , buckets AS (
        SELECT generate_series(
            date_trunc(%(bucket)s, %(start)s AT TIME ZONE %(tz)s),
            date_trunc(%(bucket)s, (%(end)s - interval '1 microsecond') AT TIME ZONE %(tz)s),
            ('1 ' || %(bucket)s)::interval
        ) AS bucket
    ),
    rs AS (
        SELECT
            date_trunc(%(bucket)s, started_at AT TIME ZONE %(tz)s) AS bucket,
            count(*) AS requests,
            count(*) FILTER (WHERE status = ANY(%(failed)s)) AS failed_requests,
            count(DISTINCT user_id) AS users,
            count(DISTINCT (user_id, session_id))
                FILTER (WHERE user_id IS NOT NULL AND session_id IS NOT NULL) AS user_sessions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
                FILTER (WHERE status = ANY(%(answered)s)) AS latency_p50_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                FILTER (WHERE status = ANY(%(answered)s)) AS latency_p95_ms,
            count(*) FILTER (WHERE user_id IS NULL) AS unidentified_requests,
            count(*) FILTER (WHERE status = ANY(%(answered)s)) AS answered_requests,
            count(*) FILTER (WHERE status = ANY(%(answered)s) AND latency_ms <= %(target_ms)s) AS within_target
        FROM r GROUP BY 1
    ),
    ss AS (
        -- sessions count in the bucket where they started
        SELECT
            date_trunc(%(bucket)s, started_at AT TIME ZONE %(tz)s) AS bucket,
            count(*) AS sessions,
            count(*) FILTER (WHERE successful) AS successful_sessions
        FROM s GROUP BY 1
    ),
    cs AS (
        SELECT
            date_trunc(%(bucket)s, request_started_at AT TIME ZONE %(tz)s) AS bucket,
            count(*) FILTER (WHERE kind = 'chat') AS chat_calls,
            count(*) FILTER (WHERE kind = 'embedding') AS embedding_calls,
            sum(cost_usd) AS cost_usd,
            coalesce(sum(cost_usd) FILTER (WHERE user_id IS NOT NULL), 0) AS identified_cost_usd
        FROM c GROUP BY 1
    )
    SELECT
        buckets.bucket,
        coalesce(rs.requests, 0) AS requests,
        coalesce(rs.failed_requests, 0) AS failed_requests,
        coalesce(rs.users, 0) AS users,
        coalesce(rs.user_sessions, 0) AS user_sessions,
        rs.latency_p50_ms,
        rs.latency_p95_ms,
        coalesce(rs.unidentified_requests, 0) AS unidentified_requests,
        coalesce(rs.answered_requests, 0) AS answered_requests,
        coalesce(rs.within_target, 0) AS within_target,
        coalesce(ss.sessions, 0) AS sessions,
        coalesce(ss.successful_sessions, 0) AS successful_sessions,
        coalesce(cs.chat_calls, 0) AS chat_calls,
        coalesce(cs.embedding_calls, 0) AS embedding_calls,
        coalesce(cs.cost_usd, 0) AS cost_usd,
        coalesce(cs.identified_cost_usd, 0) AS identified_cost_usd
    FROM buckets
    LEFT JOIN rs USING (bucket)
    LEFT JOIN ss USING (bucket)
    LEFT JOIN cs USING (bucket)
    ORDER BY buckets.bucket
"""
)

_BY_MODEL_SQL = (
    _WINDOW
    + """
    SELECT
        kind,
        model,
        count(*) AS calls,
        count(*) FILTER (WHERE NOT succeeded) AS failed_calls,
        sum(input_tokens) AS input_tokens,
        sum(output_tokens) AS output_tokens,
        sum(cost_usd) AS cost_usd,
        bool_and(priced) AS priced,
        bool_and(cost_reported) AS all_cost_reported,
        bool_or(cost_reported) AS any_cost_reported,
        bool_or(tokens_estimated) AS tokens_estimated,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms
    FROM c
    GROUP BY kind, model
    ORDER BY cost_usd DESC, calls DESC, model
"""
)

_BY_STATUS_SQL = (
    _WINDOW
    + """
    SELECT status, count(*) AS requests FROM r GROUP BY status ORDER BY requests DESC, status
"""
)

_QUALITY_RUNS_SQL = """
    SELECT run_at, samples, passed, is_demo FROM usage_quality_runs
    WHERE run_at >= %(start)s AND run_at < %(end)s ORDER BY run_at
"""

_LATEST_QUALITY_RUN_SQL = """
    SELECT run_at, samples, passed, details, is_demo FROM usage_quality_runs ORDER BY run_at DESC LIMIT 1
"""

# real (non demo) LLM spending in the calendar month containing %(now)s, in the dashboard timezone
_MONTH_SPEND_SQL = """
    SELECT coalesce(sum(c.cost_usd), 0) AS spent_usd
    FROM usage_llm_calls c JOIN usage_requests r USING (request_id)
    WHERE NOT r.is_demo
      AND r.started_at >= (date_trunc('month', %(now)s AT TIME ZONE %(tz)s) AT TIME ZONE %(tz)s)
      AND r.started_at < %(now)s
"""

_BUDGET_ALERT_SQL = """
    SELECT attempted_at, delivered, error, recipients FROM usage_budget_alerts
    WHERE month = %(month)s AND threshold_usd = %(threshold)s
"""

# Claim this month's alert: a new row, or a retry when the last attempt failed over ~an hour ago.
# Returns a row only for the caller that should send the email, so several API workers never send twice.
_CLAIM_BUDGET_ALERT_SQL = """
    INSERT INTO usage_budget_alerts (month, threshold_usd, spent_usd, recipients)
    VALUES (%(month)s, %(threshold)s, %(spent)s, %(recipients)s)
    ON CONFLICT (month, threshold_usd) DO UPDATE
        SET attempted_at = now(), spent_usd = EXCLUDED.spent_usd, recipients = EXCLUDED.recipients
        WHERE NOT usage_budget_alerts.delivered
          AND usage_budget_alerts.attempted_at < now() - interval '55 minutes'
    RETURNING month
"""

# Per user totals; requests without a user id are grouped under NULL and reported separately.
_PER_USER = """
    , per_request AS (
        SELECT request_id, count(*) AS llm_calls, sum(input_tokens) AS input_tokens,
               sum(output_tokens) AS output_tokens, sum(cost_usd) AS cost_usd
        FROM c GROUP BY request_id
    ),
    per_user AS (
        SELECT
            r.user_id,
            count(*) AS requests,
            count(DISTINCT r.session_id) AS sessions,
            coalesce(sum(pr.llm_calls), 0) AS llm_calls,
            coalesce(sum(pr.input_tokens), 0) AS input_tokens,
            coalesce(sum(pr.output_tokens), 0) AS output_tokens,
            coalesce(sum(pr.cost_usd), 0) AS cost_usd,
            min(r.started_at) AS first_seen,
            max(r.started_at) AS last_seen
        FROM r LEFT JOIN per_request pr USING (request_id)
        GROUP BY r.user_id
    )
"""

# Columns the per user table can be sorted by. Only these names are ever placed in ORDER BY.
UserSort = Literal[
    "user_id", "requests", "sessions", "llm_calls", "total_tokens", "cost_usd", "avg_cost_per_request", "last_seen"
]
USER_SORT_COLUMNS: tuple[str, ...] = UserSort.__args__  # type: ignore[attr-defined]

_USERS_SELECT = (
    _WINDOW
    + _PER_USER
    + """
    , matched AS (
        SELECT *,
            input_tokens + output_tokens AS total_tokens,
            cost_usd / nullif(requests, 0) AS avg_cost_per_request
        FROM per_user
        WHERE user_id IS NOT NULL AND user_id ILIKE %(pattern)s ESCAPE '\\'
    )
    SELECT * FROM matched
"""
)

_USERS_TOTALS_SQL = (
    _WINDOW
    + _PER_USER
    + """
    , ranked AS (
        SELECT cost_usd, row_number() OVER (ORDER BY cost_usd DESC) AS rank, count(*) OVER () AS users
        FROM per_user WHERE user_id IS NOT NULL
    )
    SELECT
        (SELECT count(*) FROM per_user WHERE user_id IS NOT NULL) AS users,
        (SELECT count(*) FROM per_user
            WHERE user_id IS NOT NULL AND user_id ILIKE %(pattern)s ESCAPE '\\') AS matched_users,
        (SELECT coalesce(sum(cost_usd), 0) FROM per_user) AS total_cost_usd,
        (SELECT sum(cost_usd) FILTER (WHERE rank <= ceil(users * 0.1)) / nullif(sum(cost_usd), 0)
            FROM ranked) AS top_decile_cost_share,
        (SELECT row_to_json(u) FROM (
            SELECT requests, sessions, llm_calls, input_tokens, output_tokens, cost_usd, first_seen, last_seen
            FROM per_user WHERE user_id IS NULL) u) AS unidentified
"""
)


class UsageStore:
    """Writes request usage rows and runs the metric queries behind the admin dashboard."""

    def __init__(
        self,
        connect: Callable[[], psycopg.Connection],
        prices: PriceTable | None = None,
    ) -> None:
        """Create a store that opens its database connection with `connect` on first use."""
        self._connect = connect
        self._prices = prices or PriceTable.load()
        self._conn: psycopg.Connection | None = None
        self._schema_ready = False
        self._unavailable_until = 0.0
        # one shared connection for writes, FastAPI runs sync endpoints on a thread pool
        self._lock = threading.Lock()

    def ensure_schema(self) -> None:
        """Create the usage tables if they do not exist yet."""
        if self._schema_ready:
            return  # common case: skip the write lock so dashboard reads never wait on chat requests
        with self._lock:
            self._ensure_schema_locked()

    def record(self, usage: RequestUsage) -> None:
        """Insert one request and its model calls, pricing each call."""
        request_row = (
            usage.request_id,
            usage.user_id,
            usage.session_id,
            usage.started_at,
            usage.latency_ms,
            usage.status,
            usage.error_type,
        )
        call_rows = []
        for call in usage.calls:
            cost, priced = self._prices.call_cost(call)
            call_rows.append(
                (
                    usage.request_id,
                    call.called_at,
                    call.kind,
                    call.model,
                    call.input_tokens,
                    call.output_tokens,
                    call.tokens_estimated,
                    cost,
                    priced,
                    call.cost_usd is not None,
                    call.latency_ms,
                    call.succeeded,
                )
            )

        def write(conn: psycopg.Connection) -> None:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO usage_requests"
                    " (request_id, user_id, session_id, started_at, latency_ms, status, error_type)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    request_row,
                )
                if call_rows:
                    cur.executemany(
                        "INSERT INTO usage_llm_calls (request_id, called_at, kind, model, input_tokens,"
                        " output_tokens, tokens_estimated, cost_usd, priced, cost_reported, latency_ms, succeeded)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        call_rows,
                    )

        self._run(write)

    def metrics(
        self,
        days: int,
        tz: str,
        bucket: Bucket | None = None,
        target_ms: int = 5000,
        budget_usd: float = 50.0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return every metric the dashboard shows for the last `days` local calendar days.

        `bucket` sets the time series granularity (default: day up to 90 days, otherwise week),
        `target_ms` the response time target, and `budget_usd` the monthly spending threshold.
        """
        start, now = _window(days, tz, now)
        previous_start = start - (now - start)
        bucket = bucket or ("day" if days <= 90 else "week")

        base = {"tz": tz, "failed": list(_FAILED), "answered": list(_ANSWERED), "target_ms": target_ms}
        window = {**base, "start": start, "end": now}

        def query(conn: psycopg.Connection) -> dict[str, Any]:
            # one transaction so every query sees the same snapshot
            with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SUMMARY_SQL, window)
                summary = cur.fetchone() or {}
                cur.execute(_SUMMARY_SQL, {**base, "start": previous_start, "end": start})
                previous = cur.fetchone() or {}
                cur.execute(_SERIES_SQL, {**window, "bucket": bucket})
                series = cur.fetchall()
                cur.execute(_BY_MODEL_SQL, window)
                by_model = cur.fetchall()
                cur.execute(_BY_STATUS_SQL, window)
                by_status = cur.fetchall()
                cur.execute(_QUALITY_RUNS_SQL, window)
                quality_runs = cur.fetchall()
                cur.execute(_LATEST_QUALITY_RUN_SQL)
                latest_quality = cur.fetchone()
            return {
                "summary": summary,
                "previous": previous,
                "series": series,
                "by_model": by_model,
                "by_status": by_status,
                "quality_runs": quality_runs,
                "latest_quality": latest_quality,
            }

        # reads use their own short lived connection so a slow dashboard query never holds up chat requests
        self.ensure_schema()  # tables may not exist yet if nothing has been recorded since the database came up
        with self._connect() as conn:
            conn.autocommit = True
            rows = query(conn)
        latest = rows["latest_quality"]
        return {
            "range": {
                "start": start.isoformat(),
                "end": now.isoformat(),
                "days": days,
                "bucket": bucket,
                "timezone": tz,
            },
            "includes_demo_data": bool(rows["summary"].get("includes_demo_data"))
            or any(run["is_demo"] for run in rows["quality_runs"]),
            "target_ms": target_ms,
            "summary": _summary(rows["summary"]),
            "previous": _summary(rows["previous"]),
            "series": [_series_point(row) for row in rows["series"]],
            "by_model": [_model_row(row) for row in rows["by_model"]],
            "by_status": [{"status": row["status"], "requests": row["requests"]} for row in rows["by_status"]],
            "quality": {
                "runs": [_quality_run(run) for run in rows["quality_runs"]],
                "latest": {**_quality_run(latest), "details": latest["details"]} if latest else None,
            },
            "budget": self.budget_status(tz, budget_usd, now=now),
        }

    def record_quality_run(self, samples: int, passed: int, details: list[dict], is_demo: bool = False) -> None:
        """Save the result of one sampled retrieval quality check."""

        def write(conn: psycopg.Connection) -> None:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO usage_quality_runs (samples, passed, details, is_demo) VALUES (%s, %s, %s, %s)",
                    (samples, passed, Jsonb(details), is_demo),
                )

        self._run(write)

    def latest_quality_run_at(self) -> datetime | None:
        """When the retrieval quality check last ran (demo runs excluded), or None if it never has."""
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT max(run_at) FROM usage_quality_runs WHERE NOT is_demo").fetchone()
        return row[0] if row else None

    def month_spend(self, tz: str, now: datetime | None = None) -> tuple[date, float]:
        """Return (first day of the current month, real LLM spending so far this month), demo data excluded."""
        zone = ZoneInfo(tz)
        now = (now or datetime.now(zone)).astimezone(zone)
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_MONTH_SPEND_SQL, {"now": now, "tz": tz})
            row = cur.fetchone() or {}
        return date(now.year, now.month, 1), float(row.get("spent_usd") or 0)

    def budget_status(self, tz: str, threshold_usd: float, now: datetime | None = None) -> dict[str, Any]:
        """Return this month's real spending against the budget, and whether an alert went out."""
        month, spent = self.month_spend(tz, now)
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_BUDGET_ALERT_SQL, {"month": month, "threshold": threshold_usd})
            alert = cur.fetchone()
        return {
            "month": month.isoformat(),
            "threshold_usd": threshold_usd,
            "spent_usd": spent,
            "used": spent / threshold_usd if threshold_usd else None,
            "alert": (
                {
                    "attempted_at": _timestamp(alert["attempted_at"]),
                    "delivered": alert["delivered"],
                    "error": alert["error"],
                    "recipients": alert["recipients"],
                }
                if alert
                else None
            ),
        }

    def claim_budget_alert(self, month: date, threshold_usd: float, spent_usd: float, recipients: str) -> bool:
        """Reserve this month's alert for the caller; False when it was already sent or is being retried elsewhere."""

        def claim(conn: psycopg.Connection) -> bool:
            with conn.transaction():
                cur = conn.execute(
                    _CLAIM_BUDGET_ALERT_SQL,
                    {"month": month, "threshold": threshold_usd, "spent": spent_usd, "recipients": recipients},
                )
                return cur.fetchone() is not None

        return self._run(claim)

    def finish_budget_alert(self, month: date, threshold_usd: float, delivered: bool, error: str | None) -> None:
        """Record whether the claimed alert email was delivered."""

        def write(conn: psycopg.Connection) -> None:
            with conn.transaction():
                conn.execute(
                    "UPDATE usage_budget_alerts SET delivered = %s, error = %s WHERE month = %s AND threshold_usd = %s",
                    (delivered, error, month, threshold_usd),
                )

        self._run(write)

    def users(
        self,
        days: int,
        tz: str,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        sort: UserSort = "cost_usd",
        descending: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return identified users' LLM usage and cost in the window, filtered by `search` and sorted by `sort`."""
        if sort not in USER_SORT_COLUMNS:
            msg = f"unsupported sort column: {sort}"
            raise ValueError(msg)

        start, now = _window(days, tz, now)
        params = {"start": start, "end": now, "limit": limit, "offset": offset, "pattern": _contains_pattern(search)}
        # the sort column comes from a fixed allowlist and is quoted as an identifier, never interpolated as text
        query = sql.SQL(
            "{select} ORDER BY {column} {direction} NULLS LAST, user_id LIMIT %(limit)s OFFSET %(offset)s"
        ).format(
            select=sql.SQL(_USERS_SELECT),  # type: ignore[arg-type]
            column=sql.Identifier(sort),
            direction=sql.SQL("DESC" if descending else "ASC"),
        )
        self.ensure_schema()
        with self._connect() as conn:
            conn.autocommit = True
            with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_USERS_TOTALS_SQL, params)
                totals = cur.fetchone() or {}
                cur.execute(query, params)
                rows = cur.fetchall()

        total_cost = float(totals.get("total_cost_usd") or 0)
        unidentified = totals.get("unidentified")
        return {
            "range": {"start": start.isoformat(), "end": now.isoformat(), "days": days, "timezone": tz},
            "total_users": totals.get("users") or 0,
            "matched_users": totals.get("matched_users") or 0,
            "search": search or None,
            "sort": sort,
            "order": "desc" if descending else "asc",
            "total_cost_usd": total_cost,
            "top_decile_cost_share": _num(totals.get("top_decile_cost_share")),
            "limit": limit,
            "offset": offset,
            "users": [_user_row(row, total_cost) for row in rows],
            "unidentified": _user_row({**unidentified, "user_id": None}, total_cost) if unidentified else None,
        }

    def close(self) -> None:
        """Close the database connection; the next operation reopens it."""
        with self._lock:
            self._close_locked()

    def _run[T](self, operation: Callable[[psycopg.Connection], T]) -> T:
        """Run `operation` on the shared connection, reconnecting once if it was dropped.

        Operations open their own transactions; the connection is in autocommit mode so it never
        sits idle inside a transaction holding locks between dashboard requests.
        """
        with self._lock:
            if time.monotonic() < self._unavailable_until:
                raise UsageStoreUnavailableError("usage database recently unreachable, skipping")
            for attempt in range(2):
                try:
                    self._ensure_schema_locked()
                    return operation(self._connection_locked())
                except psycopg.OperationalError:
                    self._close_locked()
                    if attempt == 1:
                        self._unavailable_until = time.monotonic() + _RETRY_AFTER_SECONDS
                        raise
        raise AssertionError("unreachable")

    def _connection_locked(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
            self._conn.autocommit = True
            self._schema_ready = False
        return self._conn

    def _ensure_schema_locked(self) -> None:
        conn = self._connection_locked()
        if self._schema_ready:
            return
        with conn.transaction():
            conn.execute(_SCHEMA_FILE.read_text(encoding="utf-8").encode())
        self._schema_ready = True

    def _close_locked(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._schema_ready = False


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    """Turn a summary row into the dashboard's KPIs, keeping undefined ratios as None.

    A "call" is one end to end question and answer; "model requests" are the chat and embedding
    requests made inside it.
    """
    calls = row.get("requests") or 0
    users = row.get("users") or 0
    sessions = row.get("sessions") or 0
    model_requests = (row.get("chat_calls") or 0) + (row.get("embedding_calls") or 0)
    cost = float(row.get("cost_usd") or 0)
    return {
        "calls": calls,
        "unidentified_calls": row.get("unidentified_requests") or 0,
        "failed_calls": row.get("failed_requests") or 0,
        "error_rate": _ratio(row.get("failed_requests") or 0, calls),
        "users": users,
        "sessions": sessions,
        "successful_sessions": row.get("successful_sessions") or 0,
        "successful_session_rate": _ratio(row.get("successful_sessions") or 0, sessions),
        "avg_sessions_per_user": _ratio(row.get("user_sessions") or 0, users),
        "avg_calls_per_session": _ratio(row.get("session_requests") or 0, sessions),
        "model_requests": model_requests,
        "cost_usd": cost,
        "avg_cost_per_user": _ratio(float(row.get("identified_cost_usd") or 0), users),
        "avg_cost_per_call": _ratio(cost, calls),
        "cost_per_1000_calls": _ratio(cost * 1000, calls),
        "latency_p50_ms": _num(row.get("latency_p50_ms")),
        "latency_p95_ms": _num(row.get("latency_p95_ms")),
        "within_target_rate": _ratio(row.get("within_target") or 0, row.get("answered_requests") or 0),
    }


def _series_point(row: dict[str, Any]) -> dict[str, Any]:
    users = row["users"]
    cost = float(row["cost_usd"])
    return {
        "bucket": row["bucket"].date().isoformat(),
        "calls": row["requests"],
        "unidentified_calls": row["unidentified_requests"],
        "failed_calls": row["failed_requests"],
        "error_rate": _ratio(row["failed_requests"], row["requests"]),
        "users": users,
        "sessions": row["sessions"],
        "successful_sessions": row["successful_sessions"],
        "successful_session_rate": _ratio(row["successful_sessions"], row["sessions"]),
        "avg_sessions_per_user": _ratio(row["user_sessions"], users),
        "model_requests": row["chat_calls"] + row["embedding_calls"],
        "cost_usd": cost,
        "avg_cost_per_user": _ratio(float(row["identified_cost_usd"]), users),
        "cost_per_1000_calls": _ratio(cost * 1000, row["requests"]),
        "latency_p50_ms": _num(row["latency_p50_ms"]),
        "latency_p95_ms": _num(row["latency_p95_ms"]),
        "within_target_rate": _ratio(row["within_target"], row["answered_requests"]),
    }


def _quality_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_at": _timestamp(row["run_at"]),
        "samples": row["samples"],
        "passed": row["passed"],
        "score": _ratio(row["passed"], row["samples"]),
        "is_demo": bool(row["is_demo"]),
    }


def _window(days: int, tz: str, now: datetime | None) -> tuple[datetime, datetime]:
    """Return (start, now) for the last `days` local calendar days, starting at local midnight."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(zone)).astimezone(zone)
    return datetime.combine(now.date() - timedelta(days=days - 1), datetime.min.time(), zone), now


def _contains_pattern(search: str | None) -> str:
    """ILIKE pattern matching user ids containing `search` literally (its % and _ are not wildcards)."""
    if not search:
        return "%"
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _timestamp(value: Any) -> str | None:
    """ISO string for a timestamp from a row or from row_to_json (already a string)."""
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


def _user_row(row: dict[str, Any], total_cost: float) -> dict[str, Any]:
    cost = float(row["cost_usd"] or 0)
    return {
        "user_id": row["user_id"],
        "requests": row["requests"],
        "sessions": row["sessions"],
        "llm_calls": int(row["llm_calls"] or 0),
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "cost_usd": cost,
        "cost_share": _ratio(cost, total_cost),
        "avg_cost_per_request": _ratio(cost, row["requests"]),
        "first_seen": _timestamp(row["first_seen"]),
        "last_seen": _timestamp(row["last_seen"]),
    }


def _cost_source(row: dict[str, Any]) -> str:
    """Whether a model's cost is what the provider billed, a pricing.yaml estimate, a mix, or unknown."""
    if row["all_cost_reported"]:
        return "billed"
    if not row["priced"]:
        return "unpriced"
    return "mixed" if row["any_cost_reported"] else "estimated"


def _model_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "model": row["model"],
        "calls": row["calls"],
        "failed_calls": row["failed_calls"],
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "cost_usd": float(row["cost_usd"] or 0),
        "avg_cost_per_call": _ratio(float(row["cost_usd"] or 0), row["calls"]),
        "priced": bool(row["priced"]),
        "cost_source": _cost_source(row),
        "tokens_estimated": bool(row["tokens_estimated"]),
        "latency_p50_ms": _num(row["latency_p50_ms"]),
    }


class UsageRecorder(Protocol):
    """Where tracked requests go: this Postgres store, or the AgWeatherNet backend (AwnUsageReporter)."""

    def record(self, usage: RequestUsage) -> None:
        """Save one request and its model calls."""
        ...


class UsageTracker:
    """Times a chat request, meters its model calls, and records it without ever failing the request."""

    def __init__(self, store: UsageRecorder | None) -> None:
        """Create a tracker writing to `store`, or a no-op tracker when `store` is None."""
        self._store = store

    @contextmanager
    def track(self, user_id: str | None, session_id: str | None) -> Iterator[RequestUsage]:
        """Yield the usage for one request; set `usage.status` before leaving the block."""
        usage = RequestUsage(user_id=user_id, session_id=session_id)
        started = time.perf_counter()
        try:
            with metered(usage):
                yield usage
        except BaseException as exc:
            if usage.status is None:
                usage.status = "error"
                usage.error_type = type(exc).__name__
            raise
        finally:
            usage.latency_ms = round((time.perf_counter() - started) * 1000)
            usage.status = usage.status or "ok"
            if usage.record and self._store is not None:
                try:
                    self._store.record(usage)
                except UsageStoreUnavailableError:
                    logger.debug("Skipped recording usage for request %s", usage.request_id)
                except Exception:
                    logger.warning("Failed to record usage for request %s", usage.request_id, exc_info=True)
