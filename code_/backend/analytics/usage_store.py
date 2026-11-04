"""Persist request usage in AgWeatherNet's MariaDB and compute the admin dashboard metrics.

Usage goes to the awn.table_llm_usage_* tables that AgWeatherNet created (see schema.sql). The queries only
select rows by time range; the dashboard's figures (percentiles, sessions, per day buckets in the dashboard
timezone) are computed here in Python, so nothing depends on database specific SQL or timezone tables.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import mysql.connector
from backend.analytics.metering import LlmCall, RequestUsage, metered
from mysql.connector import errors

logger = logging.getLogger("awn.analytics")

# after the database is unreachable, skip recording for this long instead of making every chat request wait
_RETRY_AFTER_SECONDS = 30

# MySQL client errors meaning the server could not be reached or the connection was lost
_CONNECTION_ERRNOS = {2002, 2003, 2005, 2006, 2013, 2055}

# column sizes in schema.sql; the server runs in strict mode, so longer text would fail the whole insert
_MODEL_MAX = 128
_ERROR_TYPE_MAX = 100
_RECIPIENTS_MAX = 512


class UsageStoreUnavailableError(RuntimeError):
    """Raised instead of writing while the database recently failed to connect."""


Bucket = Literal["day", "week", "month"]

# Requests that produced an answer count toward response time; the rest count as failures.
_ANSWERED = "ok"

# Columns the per user table can be sorted by.
UserSort = Literal[
    "user_id", "requests", "sessions", "llm_calls", "total_tokens", "cost_usd", "avg_cost_per_request", "last_seen"
]
USER_SORT_COLUMNS: tuple[str, ...] = UserSort.__args__  # type: ignore[attr-defined]

# the calls (end to end questions) started in a time range
_REQUESTS_SQL = """
    SELECT request_id, user_id, session_id, started_at, latency_ms, status, is_demo
    FROM table_llm_usage_requests WHERE started_at >= %s AND started_at < %s
"""

# the model requests made while answering those calls, attributed to their call's start time
_CALLS_SQL = """
    SELECT c.request_id, c.model, c.input_tokens, c.output_tokens, c.tokens_estimated, c.cost_usd,
           c.cost_reported, c.latency_ms, c.succeeded
    FROM table_llm_usage_model_calls c JOIN table_llm_usage_requests r ON r.request_id = c.request_id
    WHERE r.started_at >= %s AND r.started_at < %s
"""

_QUALITY_RUNS_SQL = """
    SELECT run_at, samples, passed, is_demo FROM table_llm_usage_quality_runs
    WHERE run_at >= %s AND run_at < %s ORDER BY run_at
"""

_LATEST_QUALITY_RUN_SQL = """
    SELECT run_at, samples, passed, details, is_demo FROM table_llm_usage_quality_runs ORDER BY run_at DESC LIMIT 1
"""

# real (non demo) chat spending between two UTC times
_SPEND_SQL = """
    SELECT COALESCE(SUM(c.cost_usd), 0)
    FROM table_llm_usage_model_calls c JOIN table_llm_usage_requests r ON r.request_id = c.request_id
    WHERE r.is_demo = 0 AND r.started_at >= %s AND r.started_at < %s
"""

_BUDGET_ALERT_SQL = """
    SELECT attempted_at, delivered, error, recipients FROM table_llm_usage_budget_alerts
    WHERE month = %s AND threshold_usd = %s
"""

# Claiming this month's alert: the first caller inserts the row; later callers can only take it over to retry
# a failed send that is about an hour old. Each statement is atomic, so several API workers (or both AWN
# servers) never send the same alert twice.
_INSERT_BUDGET_ALERT_SQL = """
    INSERT IGNORE INTO table_llm_usage_budget_alerts (month, threshold_usd, spent_usd, recipients, attempted_at)
    VALUES (%s, %s, %s, %s, UTC_TIMESTAMP())
"""
_RETRY_BUDGET_ALERT_SQL = """
    UPDATE table_llm_usage_budget_alerts
    SET attempted_at = UTC_TIMESTAMP(), spent_usd = %s, recipients = %s
    WHERE month = %s AND threshold_usd = %s AND delivered = 0
      AND attempted_at < UTC_TIMESTAMP() - INTERVAL 55 MINUTE
"""


@dataclass(frozen=True)
class UsageDatabaseConfig:
    """Connection settings for the AgWeatherNet database holding the usage tables."""

    user: str
    password: str
    host: str
    port: int = 3306
    database: str = "awn"

    @classmethod
    def from_env(cls) -> UsageDatabaseConfig | None:
        """Read AWN_USAGE_DB_*; None when no usage database account is configured.

        The account is separate from AWN_DB_USER on purpose: the chatbot runs model written SQL with that
        account, so it stays read only, while this one can only write the usage tables.
        """
        user = os.getenv("AWN_USAGE_DB_USER", "").strip()
        if not user:
            return None
        host = os.getenv("AWN_USAGE_DB_HOST", "").strip() or os.getenv("AWN_DB_HOST", "").strip()
        if not host:
            raise ValueError("AWN_USAGE_DB_USER is set but neither AWN_USAGE_DB_HOST nor AWN_DB_HOST is")
        return cls(
            user=user,
            password=os.getenv("AWN_USAGE_DB_PASSWORD", ""),
            host=host,
            port=int(os.getenv("AWN_USAGE_DB_PORT") or 3306),
            database=os.getenv("AWN_USAGE_DB_NAME", "").strip() or "awn",
        )

    def connect(self, timeout: int = 3) -> Any:
        """Open an autocommit connection whose session time zone is UTC, matching the stored timestamps."""
        return mysql.connector.connect(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            connection_timeout=timeout,
            autocommit=True,
            time_zone="+00:00",
        )


class UsageStore:
    """Writes request usage rows and runs the metric queries behind the admin dashboard."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        """Create a store that opens its database connections with `connect` (a MySQL connection factory)."""
        self._connect = connect
        self._conn: Any = None
        self._unavailable_until = 0.0
        # one shared connection for writes, FastAPI runs sync endpoints on a thread pool
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> UsageStore | None:
        """Create a store for the database in AWN_USAGE_DB_*, or return None when it is not configured."""
        config = UsageDatabaseConfig.from_env()
        return cls(config.connect) if config else None

    def record(self, usage: RequestUsage) -> None:
        """Insert one request and its model calls, at the cost OpenRouter reported for each call."""
        request_id = str(usage.request_id)
        request_row = (
            request_id,
            usage.user_id,
            usage.session_id,
            _utc(usage.started_at),
            usage.latency_ms,
            usage.status,
            usage.error_type[:_ERROR_TYPE_MAX] if usage.error_type else None,
        )
        call_rows = []
        for call in usage.calls:
            reported = call.cost_usd is not None
            call_rows.append(
                (
                    request_id,
                    _utc(call.called_at),
                    call.model[:_MODEL_MAX],
                    call.input_tokens,
                    call.output_tokens,
                    call.tokens_estimated,
                    call.cost_usd or 0.0,
                    reported,  # priced: the cost is known exactly when OpenRouter reported it
                    reported,
                    call.latency_ms,
                    call.succeeded,
                )
            )

        def write(conn: Any) -> None:
            with _transaction(conn), closing(conn.cursor()) as cur:
                cur.execute(
                    "INSERT INTO table_llm_usage_requests"
                    " (request_id, user_id, session_id, started_at, latency_ms, status, error_type)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    request_row,
                )
                if call_rows:
                    cur.executemany(
                        "INSERT INTO table_llm_usage_model_calls (request_id, called_at, kind, model, input_tokens,"
                        " output_tokens, tokens_estimated, cost_usd, priced, cost_reported, latency_ms, succeeded)"
                        " VALUES (%s, %s, 'chat', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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

        # reads use their own short lived connection so a slow dashboard query never holds up chat requests
        with self._read() as cur:
            usage = _fetch_usage(cur, previous_start, now)
            cur.execute(_QUALITY_RUNS_SQL, (_utc(start), _utc(now)))
            quality_runs = cur.fetchall()
            cur.execute(_LATEST_QUALITY_RUN_SQL)
            latest = cur.fetchone()

        current = usage.between(start, now)
        previous = usage.between(previous_start, start)
        return {
            "range": {
                "start": start.isoformat(),
                "end": now.isoformat(),
                "days": days,
                "bucket": bucket,
                "timezone": tz,
            },
            "includes_demo_data": any(r["is_demo"] for r in current.requests)
            or any(run["is_demo"] for run in quality_runs),
            "target_ms": target_ms,
            "summary": _summary(current, target_ms),
            "previous": _summary(previous, target_ms),
            "series": _series(current, start, now, ZoneInfo(tz), bucket, target_ms),
            "by_model": _by_model(current),
            "by_status": [
                {"status": status, "requests": count}
                for status, count in sorted(
                    Counter(r["status"] for r in current.requests).items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "quality": {
                "runs": [_quality_run(run) for run in quality_runs],
                "latest": {**_quality_run(latest), "details": json.loads(latest["details"])} if latest else None,
            },
            "budget": self.budget_status(tz, budget_usd, now=now),
        }

    def record_quality_run(
        self,
        samples: int,
        passed: int,
        details: list[dict],
        is_demo: bool = False,
        calls: Sequence[LlmCall] = (),
    ) -> None:
        """Save the result of one sampled retrieval quality check.

        `calls` (the check's model requests) are accepted for the same interface as AwnUsageReporter, but the
        quality runs table has no cost column, so their cost is not stored.
        """

        def write(conn: Any) -> None:
            with _transaction(conn), closing(conn.cursor()) as cur:
                cur.execute(
                    "INSERT INTO table_llm_usage_quality_runs (run_at, samples, passed, details, is_demo)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (_utc(datetime.now(UTC)), samples, passed, json.dumps(details), is_demo),
                )

        self._run(write)

    def latest_quality_run_at(self) -> datetime | None:
        """When the retrieval quality check last ran (demo runs excluded), or None if it never has."""
        with self._read() as cur:
            cur.execute("SELECT MAX(run_at) AS run_at FROM table_llm_usage_quality_runs WHERE is_demo = 0")
            row = cur.fetchone()
        return _from_utc(row["run_at"]) if row else None

    def month_spend(self, tz: str, now: datetime | None = None) -> tuple[date, float]:
        """Return (first day of the current month, real LLM spending so far this month), demo data excluded."""
        zone = ZoneInfo(tz)
        now = (now or datetime.now(zone)).astimezone(zone)
        month = date(now.year, now.month, 1)
        month_start = datetime.combine(month, datetime.min.time(), zone)
        with self._read() as cur:
            cur.execute(_SPEND_SQL, (_utc(month_start), _utc(now)))
            row = cur.fetchone()
        return month, float(next(iter(row.values())) if row else 0)

    def budget_status(self, tz: str, threshold_usd: float, now: datetime | None = None) -> dict[str, Any]:
        """Return this month's real spending against the budget, and whether an alert went out."""
        month, spent = self.month_spend(tz, now)
        with self._read() as cur:
            cur.execute(_BUDGET_ALERT_SQL, (month, threshold_usd))
            alert = cur.fetchone()
        return {
            "month": month.isoformat(),
            "threshold_usd": threshold_usd,
            "spent_usd": spent,
            "used": spent / threshold_usd if threshold_usd else None,
            "alert": (
                {
                    "attempted_at": _timestamp(alert["attempted_at"]),
                    "delivered": bool(alert["delivered"]),
                    "error": alert["error"],
                    "recipients": alert["recipients"],
                }
                if alert
                else None
            ),
        }

    def claim_budget_alert(self, month: date, threshold_usd: float, spent_usd: float, recipients: str) -> bool:
        """Reserve this month's alert for the caller; False when it was already sent or is being retried elsewhere."""
        recipients = recipients[:_RECIPIENTS_MAX]

        def claim(conn: Any) -> bool:
            with closing(conn.cursor()) as cur:
                cur.execute(_INSERT_BUDGET_ALERT_SQL, (month, threshold_usd, spent_usd, recipients))
                if cur.rowcount == 1:
                    return True
                cur.execute(_RETRY_BUDGET_ALERT_SQL, (spent_usd, recipients, month, threshold_usd))
                return cur.rowcount == 1

        return self._run(claim)

    def finish_budget_alert(self, month: date, threshold_usd: float, delivered: bool, error: str | None) -> None:
        """Record whether the claimed alert email was delivered."""

        def write(conn: Any) -> None:
            with closing(conn.cursor()) as cur:
                cur.execute(
                    "UPDATE table_llm_usage_budget_alerts SET delivered = %s, error = %s"
                    " WHERE month = %s AND threshold_usd = %s",
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
        with self._read() as cur:
            usage = _fetch_usage(cur, start, now)

        per_user = _per_user(usage)
        identified = [row for user_id, row in per_user.items() if user_id is not None]
        total_cost = sum(row["cost_usd"] for row in per_user.values())
        needle = (search or "").casefold()
        matched = [row for row in identified if needle in row["user_id"].casefold()]
        unidentified = per_user.get(None)
        return {
            "range": {"start": start.isoformat(), "end": now.isoformat(), "days": days, "timezone": tz},
            "total_users": len(identified),
            "matched_users": len(matched),
            "search": search or None,
            "sort": sort,
            "order": "desc" if descending else "asc",
            "total_cost_usd": total_cost,
            "top_decile_cost_share": _top_decile_share(identified),
            "limit": limit,
            "offset": offset,
            "users": [_user_row(row, total_cost) for row in _sorted_users(matched, sort, descending)][
                offset : offset + limit
            ],
            "unidentified": _user_row(unidentified, total_cost) if unidentified else None,
        }

    def close(self) -> None:
        """Close the write connection; the next write reopens it."""
        with self._lock:
            self._close_locked()

    @contextmanager
    def _read(self) -> Iterator[Any]:
        """Yield a dictionary cursor on a new connection, inside one read only snapshot."""
        with closing(self._connect()) as conn, closing(conn.cursor(dictionary=True)) as cur:
            # as SQL: the connector's readonly flag rejects MariaDB, which reports itself as version 5.5.5
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            try:
                yield cur
            finally:
                conn.rollback()

    def _run[T](self, operation: Callable[[Any], T]) -> T:
        """Run a write `operation` on the shared connection, reconnecting once if it was dropped."""
        with self._lock:
            if time.monotonic() < self._unavailable_until:
                raise UsageStoreUnavailableError("usage database recently unreachable, skipping")
            for attempt in range(2):
                try:
                    return operation(self._connection_locked())
                except errors.Error as exc:
                    if not _is_connection_error(exc):
                        raise
                    self._close_locked()
                    if attempt == 1:
                        self._unavailable_until = time.monotonic() + _RETRY_AFTER_SECONDS
                        raise
        raise AssertionError("unreachable")

    def _connection_locked(self) -> Any:
        if self._conn is None or not self._conn.is_connected():
            self._close_locked()
            self._conn = self._connect()
        return self._conn

    def _close_locked(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except errors.Error:
                pass  # already gone
            finally:
                self._conn = None


@contextmanager
def _transaction(conn: Any) -> Iterator[None]:
    """Run the block in a transaction on an autocommit connection."""
    conn.start_transaction()
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _is_connection_error(exc: errors.Error) -> bool:
    return isinstance(exc, (errors.OperationalError, errors.InterfaceError)) or exc.errno in _CONNECTION_ERRNOS


def _utc(value: datetime) -> datetime:
    """Convert to naive UTC, as the DATETIME columns store it."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _from_utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


@dataclass
class _Usage:
    """Requests in a time range and the model requests made while answering them."""

    requests: list[dict[str, Any]]
    calls: list[dict[str, Any]]

    def between(self, start: datetime, end: datetime) -> _Usage:
        requests = [r for r in self.requests if start <= r["started_at"] < end]
        ids = {r["request_id"] for r in requests}
        return _Usage(requests, [c for c in self.calls if c["request_id"] in ids])

    def calls_by_request(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for call in self.calls:
            grouped[call["request_id"]].append(call)
        return grouped


def _fetch_usage(cur: Any, start: datetime, end: datetime) -> _Usage:
    cur.execute(_REQUESTS_SQL, (_utc(start), _utc(end)))
    requests = cur.fetchall()
    for row in requests:
        row["started_at"] = _from_utc(row["started_at"])
    cur.execute(_CALLS_SQL, (_utc(start), _utc(end)))
    calls = cur.fetchall()
    for row in calls:
        row["cost_usd"] = float(row["cost_usd"])
    return _Usage(requests, calls)


def _percentile(values: Iterable[float | None], fraction: float) -> float | None:
    """Continuous percentile (linear interpolation, like SQL percentile_cont); None for no values."""
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _sessions(requests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Login sessions with calls in `requests`: when each started, and whether every call was answered."""
    sessions: dict[str, dict[str, Any]] = {}
    for r in requests:
        if r["session_id"] is None:
            continue
        session = sessions.setdefault(r["session_id"], {"started_at": r["started_at"], "successful": True})
        session["started_at"] = min(session["started_at"], r["started_at"])
        session["successful"] = session["successful"] and r["status"] == _ANSWERED
    return sessions


def _kpis(usage: _Usage, target_ms: int, sessions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute the KPIs for some calls (one end to end question each) and the login `sessions` they count.

    "Model requests" are the model requests made inside those calls.
    """
    requests = usage.requests
    calls = len(requests)
    users = len({r["user_id"] for r in requests if r["user_id"] is not None})
    sessions = list(sessions)
    successful_sessions = sum(1 for s in sessions if s["successful"])
    failed = sum(1 for r in requests if r["status"] != _ANSWERED)
    answered = [r["latency_ms"] for r in requests if r["status"] == _ANSWERED]
    identified = {r["request_id"] for r in requests if r["user_id"] is not None}
    cost = sum(c["cost_usd"] for c in usage.calls)
    identified_cost = sum(c["cost_usd"] for c in usage.calls if c["request_id"] in identified)
    user_sessions = {(r["user_id"], r["session_id"]) for r in requests if r["user_id"] and r["session_id"]}
    return {
        "calls": calls,
        "unidentified_calls": sum(1 for r in requests if r["user_id"] is None),
        "failed_calls": failed,
        "error_rate": _ratio(failed, calls),
        "users": users,
        "sessions": len(sessions),
        "successful_sessions": successful_sessions,
        "successful_session_rate": _ratio(successful_sessions, len(sessions)),
        "avg_sessions_per_user": _ratio(len(user_sessions), users),
        "model_requests": len(usage.calls),
        "cost_usd": cost,
        "avg_cost_per_user": _ratio(identified_cost, users),
        "cost_per_1000_calls": _ratio(cost * 1000, calls),
        "latency_p50_ms": _percentile(answered, 0.5),
        "latency_p95_ms": _percentile(answered, 0.95),
        "within_target_rate": _ratio(sum(1 for ms in answered if ms <= target_ms), len(answered)),
    }


def _summary(usage: _Usage, target_ms: int) -> dict[str, Any]:
    kpis = _kpis(usage, target_ms, _sessions(usage.requests).values())
    session_requests = sum(1 for r in usage.requests if r["session_id"] is not None)
    return {
        **kpis,
        "avg_cost_per_call": _ratio(kpis["cost_usd"], kpis["calls"]),
        "avg_calls_per_session": _ratio(session_requests, kpis["sessions"]),
    }


def _bucket_start(moment: datetime, zone: ZoneInfo, bucket: Bucket) -> date:
    day = moment.astimezone(zone).date()
    if bucket == "week":
        return day - timedelta(days=day.weekday())  # weeks start on Monday
    if bucket == "month":
        return day.replace(day=1)
    return day


def _next_bucket(day: date, bucket: Bucket) -> date:
    if bucket == "day":
        return day + timedelta(days=1)
    if bucket == "week":
        return day + timedelta(weeks=1)
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def _series(usage: _Usage, start: datetime, end: datetime, zone: ZoneInfo, bucket: Bucket, target_ms: int) -> list:
    """One point per day, week or month in the window, including empty ones; sessions count where they started."""
    requests: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for r in usage.requests:
        requests[_bucket_start(r["started_at"], zone, bucket)].append(r)
    sessions: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for session in _sessions(usage.requests).values():
        sessions[_bucket_start(session["started_at"], zone, bucket)].append(session)
    calls = usage.calls_by_request()

    points = []
    day = _bucket_start(start, zone, bucket)
    last = _bucket_start(end - timedelta(microseconds=1), zone, bucket)
    while day <= last:
        in_bucket = requests.get(day, [])
        bucket_calls = [c for r in in_bucket for c in calls.get(r["request_id"], [])]
        kpis = _kpis(_Usage(in_bucket, bucket_calls), target_ms, sessions.get(day, []))
        points.append({"bucket": day.isoformat(), **kpis})
        day = _next_bucket(day, bucket)
    return points


def _cost_source(calls: list[dict[str, Any]]) -> str:
    """Whether OpenRouter reported the cost of all, some, or none of a model's requests."""
    reported = [bool(c["cost_reported"]) for c in calls]
    if all(reported):
        return "billed"
    return "mixed" if any(reported) else "unreported"


def _by_model(usage: _Usage) -> list[dict[str, Any]]:
    models: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in usage.calls:
        models[call["model"]].append(call)
    rows = []
    for model, calls in models.items():
        cost = sum(c["cost_usd"] for c in calls)
        rows.append(
            {
                "model": model,
                "calls": len(calls),
                "failed_calls": sum(1 for c in calls if not c["succeeded"]),
                "input_tokens": sum(c["input_tokens"] for c in calls),
                "output_tokens": sum(c["output_tokens"] for c in calls),
                "cost_usd": cost,
                "avg_cost_per_call": _ratio(cost, len(calls)),
                "cost_source": _cost_source(calls),
                "tokens_estimated": any(c["tokens_estimated"] for c in calls),
                "latency_p50_ms": _percentile((c["latency_ms"] for c in calls), 0.5),
            }
        )
    return sorted(rows, key=lambda row: (-row["cost_usd"], -row["calls"], row["model"]))


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


def _timestamp(value: datetime | None) -> str | None:
    """ISO string for a UTC timestamp from the database (naive) or already converted (aware)."""
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _per_user(usage: _Usage) -> dict[str | None, dict[str, Any]]:
    """Totals per user id; requests without a user id are grouped under None."""
    calls = usage.calls_by_request()
    users: dict[str | None, dict[str, Any]] = {}
    sessions: dict[str | None, set[str]] = defaultdict(set)
    for r in usage.requests:
        row = users.setdefault(
            r["user_id"],
            {
                "user_id": r["user_id"],
                "requests": 0,
                "llm_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "first_seen": r["started_at"],
                "last_seen": r["started_at"],
            },
        )
        row["requests"] += 1
        row["first_seen"] = min(row["first_seen"], r["started_at"])
        row["last_seen"] = max(row["last_seen"], r["started_at"])
        if r["session_id"] is not None:
            sessions[r["user_id"]].add(r["session_id"])
        for call in calls.get(r["request_id"], []):
            row["llm_calls"] += 1
            row["input_tokens"] += call["input_tokens"]
            row["output_tokens"] += call["output_tokens"]
            row["cost_usd"] += call["cost_usd"]
    for user_id, row in users.items():
        row["sessions"] = len(sessions[user_id])
        row["total_tokens"] = row["input_tokens"] + row["output_tokens"]
        row["avg_cost_per_request"] = _ratio(row["cost_usd"], row["requests"])
    return users


def _sorted_users(rows: list[dict[str, Any]], sort: str, descending: bool) -> list[dict[str, Any]]:
    """Sort by `sort` with empty values last; ties keep user id order."""
    by_id = sorted(rows, key=lambda row: (row["user_id"].casefold(), row["user_id"]))
    if sort == "user_id":
        return by_id[::-1] if descending else by_id
    present = [row for row in by_id if row[sort] is not None]
    present.sort(key=lambda row: row[sort], reverse=descending)  # stable, so ties stay in user id order
    return present + [row for row in by_id if row[sort] is None]


def _top_decile_share(identified: list[dict[str, Any]]) -> float | None:
    """Share of identified users' cost spent by the most expensive 10% of them (at least one user)."""
    costs = sorted((row["cost_usd"] for row in identified), reverse=True)
    total = sum(costs)
    if not total:
        return None
    return sum(costs[: math.ceil(len(costs) * 0.1)]) / total


def _user_row(row: dict[str, Any], total_cost: float) -> dict[str, Any]:
    cost = row["cost_usd"]
    return {
        "user_id": row["user_id"],
        "requests": row["requests"],
        "sessions": row["sessions"],
        "llm_calls": row["llm_calls"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cost_usd": cost,
        "cost_share": _ratio(cost, total_cost),
        "avg_cost_per_request": row["avg_cost_per_request"],
        "first_seen": _timestamp(row["first_seen"]),
        "last_seen": _timestamp(row["last_seen"]),
    }


class UsageRecorder(Protocol):
    """Where tracked requests go: this database store, or the AgWeatherNet backend (AwnUsageReporter)."""

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
