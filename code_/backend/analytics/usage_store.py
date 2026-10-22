"""Persist request usage and compute the admin dashboard metrics."""

from __future__ import annotations

import logging
import pathlib
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from backend.analytics.metering import RequestUsage, metered
from backend.analytics.pricing import PriceTable
from psycopg import sql
from psycopg.rows import dict_row

logger = logging.getLogger("awn.analytics")

_SCHEMA_FILE = pathlib.Path(__file__).with_name("schema.sql")

# after the database is unreachable, skip recording for this long instead of making every chat request wait
_RETRY_AFTER_SECONDS = 30


class UsageStoreUnavailableError(RuntimeError):
    """Raised instead of writing while the database recently failed to connect."""


Bucket = Literal["day", "week", "month"]

# Requests that produced an answer count toward response time; the rest count as failures.
_ANSWERED = ("ok", "empty")
_FAILED = ("error", "rate_limited", "unavailable")

# Shared CTEs: `r` is the requests in the window, `c` the model calls made by those requests.
# Calls are attributed to their request's start time so cost and request counts always agree.
_WINDOW = """
    WITH r AS (
        SELECT * FROM usage_requests WHERE started_at >= %(start)s AND started_at < %(end)s
    ),
    c AS (
        SELECT usage_llm_calls.*, r.user_id, r.started_at AS request_started_at
        FROM usage_llm_calls JOIN r USING (request_id)
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
        (SELECT count(DISTINCT session_id) FROM r) AS sessions,
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
                FILTER (WHERE status = ANY(%(answered)s)) AS latency_p95_ms
        FROM r GROUP BY 1
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
        coalesce(cs.chat_calls, 0) AS chat_calls,
        coalesce(cs.embedding_calls, 0) AS embedding_calls,
        coalesce(cs.cost_usd, 0) AS cost_usd,
        coalesce(cs.identified_cost_usd, 0) AS identified_cost_usd
    FROM buckets
    LEFT JOIN rs USING (bucket)
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
            if call.cost_usd is not None:
                # the provider told us what it billed; no estimate needed
                cost, priced = call.cost_usd, True
            else:
                cost, priced = self._prices.cost(call.model, call.input_tokens, call.output_tokens)
            if not priced and call.requested_model and call.requested_model != call.model:
                # routers (e.g. openrouter/free) answer with another model's name; fall back to the configured one
                cost, priced = self._prices.cost(call.requested_model, call.input_tokens, call.output_tokens)
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

    def metrics(self, days: int, tz: str, now: datetime | None = None) -> dict[str, Any]:
        """Return every metric the dashboard shows for the last `days` local calendar days."""
        start, now = _window(days, tz, now)
        previous_start = start - (now - start)
        # months are always whole calendar months so monthly users are comparable
        month_start = start.replace(day=1)
        bucket: Bucket = "day" if days <= 90 else "week"

        base = {"tz": tz, "failed": list(_FAILED), "answered": list(_ANSWERED)}
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
                cur.execute(_SERIES_SQL, {**base, "start": month_start, "end": now, "bucket": "month"})
                months = cur.fetchall()
                cur.execute(_BY_MODEL_SQL, window)
                by_model = cur.fetchall()
                cur.execute(_BY_STATUS_SQL, window)
                by_status = cur.fetchall()
            return {
                "summary": summary,
                "previous": previous,
                "series": series,
                "months": months,
                "by_model": by_model,
                "by_status": by_status,
            }

        # reads use their own short lived connection so a slow dashboard query never holds up chat requests
        self.ensure_schema()  # tables may not exist yet if nothing has been recorded since the database came up
        with self._connect() as conn:
            conn.autocommit = True
            rows = query(conn)
        current_month = date(now.year, now.month, 1)
        return {
            "range": {
                "start": start.isoformat(),
                "end": now.isoformat(),
                "days": days,
                "bucket": bucket,
                "timezone": tz,
            },
            "includes_demo_data": bool(rows["summary"].get("includes_demo_data")),
            "summary": _summary(rows["summary"]),
            "previous": _summary(rows["previous"]),
            "series": [_series_point(row) for row in rows["series"]],
            "months": [
                {**_series_point(row), "partial": row["bucket"].date() >= current_month} for row in rows["months"]
            ],
            "by_model": [_model_row(row) for row in rows["by_model"]],
            "by_status": [{"status": row["status"], "requests": row["requests"]} for row in rows["by_status"]],
        }

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
    """Turn a summary row into the dashboard's KPIs, keeping undefined ratios as None."""
    requests = row.get("requests") or 0
    users = row.get("users") or 0
    sessions = row.get("sessions") or 0
    chat_calls = row.get("chat_calls") or 0
    embedding_calls = row.get("embedding_calls") or 0
    llm_calls = chat_calls + embedding_calls
    cost = float(row.get("cost_usd") or 0)
    return {
        "requests": requests,
        "unidentified_requests": row.get("unidentified_requests") or 0,
        "failed_requests": row.get("failed_requests") or 0,
        "error_rate": _ratio(row.get("failed_requests") or 0, requests),
        "users": users,
        "sessions": sessions,
        "avg_sessions_per_user": _ratio(row.get("user_sessions") or 0, users),
        "avg_requests_per_session": _ratio(row.get("session_requests") or 0, sessions),
        "chat_calls": chat_calls,
        "embedding_calls": embedding_calls,
        "llm_calls": llm_calls,
        "cost_usd": cost,
        "avg_cost_per_user": _ratio(float(row.get("identified_cost_usd") or 0), users),
        "avg_cost_per_call": _ratio(cost, llm_calls),
        "avg_cost_per_request": _ratio(cost, requests),
        "latency_p50_ms": _num(row.get("latency_p50_ms")),
        "latency_p95_ms": _num(row.get("latency_p95_ms")),
    }


def _series_point(row: dict[str, Any]) -> dict[str, Any]:
    users = row["users"]
    cost = float(row["cost_usd"])
    return {
        "bucket": row["bucket"].date().isoformat(),
        "requests": row["requests"],
        "failed_requests": row["failed_requests"],
        "error_rate": _ratio(row["failed_requests"], row["requests"]),
        "users": users,
        "avg_sessions_per_user": _ratio(row["user_sessions"], users),
        "chat_calls": row["chat_calls"],
        "embedding_calls": row["embedding_calls"],
        "llm_calls": row["chat_calls"] + row["embedding_calls"],
        "cost_usd": cost,
        "avg_cost_per_user": _ratio(float(row["identified_cost_usd"]), users),
        "latency_p50_ms": _num(row["latency_p50_ms"]),
        "latency_p95_ms": _num(row["latency_p95_ms"]),
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


class UsageTracker:
    """Times a chat request, meters its model calls, and records it without ever failing the request."""

    def __init__(self, store: UsageStore | None) -> None:
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
