"""Fill the usage tables with synthetic traffic so the admin dashboard can be previewed.

Generates signed-in users (signing in is required to use the chatbot) with 2 day login sessions, the
LangGraph workflow's chat requests for each question (classifier, SQL, summary), and a daily retrieval
quality check. Rows are flagged is_demo: the dashboard shows a "Demo data" badge while any
are in range, and demo spending never counts toward the monthly budget alert.

    python -m scripts.seed_dashboard_demo            # add ~120 days of demo traffic
    python -m scripts.seed_dashboard_demo --clear    # remove all demo rows
"""

import argparse
import math
import random
import uuid
from datetime import UTC, datetime, timedelta

import dotenv
from backend.analytics.retrieval_quality import load_samples
from backend.analytics.usage_store import UsageStore
from backend.databases.pgvector import PgVectorConnection
from psycopg.types.json import Jsonb

# made up prices for the demo chat model, USD per 1M tokens, so cost charts have something to show
_DEMO_CHAT_MODEL = ("demo/chat-model", 0.10, 0.40)
# the LangGraph workflow's chat requests for one question: (step, input tokens, output tokens, share of latency)
_WORKFLOW_STEPS = (
    ("classifier", (500, 900), (40, 120), 0.2),
    ("sql", (900, 1_600), (40, 140), 0.3),
    ("summary", (700, 1_800), (60, 320), 0.5),
)
_SESSION_LENGTH = timedelta(days=2)  # login sessions expire after 2 days


def _clear(conn) -> tuple[int, int]:
    with conn.transaction():
        requests = conn.execute("DELETE FROM usage_requests WHERE is_demo").rowcount
        runs = conn.execute("DELETE FROM usage_quality_runs WHERE is_demo").rowcount
    return requests, runs


def _seed(conn, days: int, max_daily_users: int, rng: random.Random) -> int:
    now = datetime.now(UTC)
    user_pool = [f"demo-user-{i}" for i in range(max_daily_users * 6)]
    requests, calls = [], []

    sessions: dict[str, tuple[str, datetime]] = {}  # user -> (login session id, expires at)
    quality_runs = []

    def login_session(user: str, at: datetime) -> str:
        """Reuse the user's login session until it expires, then log them in again."""
        current = sessions.get(user)
        if current is None or current[1] <= at:
            current = (f"demo-session-{uuid.uuid4().hex[:12]}", at + _SESSION_LENGTH)
            sessions[user] = current
        return current[0]

    def visit(user: str, day_start: datetime, incident: bool) -> None:
        started = day_start + timedelta(seconds=rng.uniform(6 * 3600, 22 * 3600))
        for _ in range(max(1, round(rng.lognormvariate(1.0, 0.6)))):
            started += timedelta(seconds=rng.uniform(20, 240))
            if started >= now:
                return
            session = login_session(user, started)
            _add_request(requests, calls, user, session, started, incident, rng)

    for day in range(days, 0, -1):
        day_start = (now - timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        growth = 0.35 + 0.65 * (1 - day / days)  # traffic grows over the period
        weekday = 0.6 if day_start.weekday() >= 5 else 1.0  # quieter weekends
        daily_users = max(1, int(max_daily_users * growth * weekday * rng.uniform(0.8, 1.2)))
        # a slow provider day every few weeks shows up as a latency and error spike
        incident = rng.random() < 0.05

        for user in rng.sample(user_pool[: int(len(user_pool) * growth) or 1], daily_users):
            for _ in range(rng.choices([1, 2, 3], weights=[70, 22, 8])[0]):
                visit(user, day_start, incident)

        quality_runs.append(_quality_run(day_start + timedelta(hours=10), incident, rng))

    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO usage_requests (request_id, user_id, session_id, started_at, latency_ms, status,"
            " error_type, is_demo) VALUES (%s, %s, %s, %s, %s, %s, %s, true)",
            requests,
        )
        cur.executemany(
            "INSERT INTO usage_llm_calls (request_id, called_at, kind, model, input_tokens, output_tokens,"
            " tokens_estimated, cost_usd, priced, latency_ms, succeeded)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)",
            calls,
        )
        cur.executemany(
            "INSERT INTO usage_quality_runs (run_at, samples, passed, details, is_demo) VALUES (%s, %s, %s, %s, true)",
            quality_runs,
        )
    return len(requests)


def _quality_run(run_at: datetime, incident: bool, rng: random.Random) -> tuple:
    """Build one daily retrieval quality check: most sample questions pass, fewer on a bad provider day."""
    samples = load_samples()
    misses = rng.choices([0, 1, 2], weights=[55, 35, 10])[0] + (rng.randint(2, 4) if incident else 0)
    missed = set(rng.sample(range(len(samples)), min(misses, len(samples))))
    details = [
        {
            "question": sample.question,
            "source": sample.source,
            "expected": sample.station,
            "passed": i not in missed,
            # like the real check: what the workflow read, or the right kind of data with no records
            "found": [f"{sample.source}: {0 if i in missed else rng.randint(1, 7)} rows"],
            "error": None,
        }
        for i, sample in enumerate(samples)
    ]
    return (run_at, len(samples), len(samples) - len(missed), Jsonb(details))


def _add_request(requests: list, calls: list, user, session, started, incident: bool, rng) -> None:
    request_id = uuid.uuid4()
    roll = rng.random()
    failure_rate = 0.12 if incident else 0.015
    if roll < failure_rate:
        status, error = rng.choice([("rate_limited", "TooManyRequestsResponseError"), ("error", "RuntimeError")])
    elif roll < failure_rate + 0.04:
        status, error = "empty", None
    else:
        status, error = "ok", None

    chat_latency = int(rng.lognormvariate(math.log(4_200 if incident else 1_400), 0.45))
    model, price_in, price_out = _DEMO_CHAT_MODEL
    # an errored call stops after the classifier; a rate-limited one is refused at the summary
    steps = _WORKFLOW_STEPS[:1] if status == "error" else _WORKFLOW_STEPS
    called_at = started
    for step, (in_low, in_high), (out_low, out_high), share in steps:
        tokens_in, tokens_out = rng.randint(in_low, in_high), rng.randint(out_low, out_high)
        succeeded = not (status == "rate_limited" and step == "summary")
        if not succeeded:
            tokens_in = tokens_out = 0
        cost = (tokens_in * price_in + tokens_out * price_out) / 1e6
        latency = int(chat_latency * share)
        calls.append((request_id, called_at, "chat", model, tokens_in, tokens_out, False, cost, latency, succeeded))
        called_at += timedelta(milliseconds=latency)

    latency = chat_latency + rng.randint(150, 600)
    requests.append((request_id, user, session, started, latency, status, error))


def main() -> None:
    """Seed or clear demo usage data."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=120, help="days of history to generate (default 120)")
    parser.add_argument("--users", type=int, default=60, help="peak daily active users (default 60)")
    parser.add_argument("--seed", type=int, default=15, help="random seed for repeatable data")
    parser.add_argument("--clear", action="store_true", help="delete all demo rows instead of adding them")
    args = parser.parse_args()

    dotenv.load_dotenv()
    UsageStore(lambda: PgVectorConnection().conn).ensure_schema()

    with PgVectorConnection() as db:
        conn = db.conn
        conn.autocommit = True
        if args.clear:
            requests, runs = _clear(conn)
            print(f"Removed {requests} demo calls and {runs} demo quality checks.")
            return
        created = _seed(conn, args.days, args.users, random.Random(args.seed))
        print(f"Added {created} demo calls over {args.days} days. Remove them with --clear.")


if __name__ == "__main__":
    main()
