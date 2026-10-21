"""Fill the usage tables with synthetic traffic so the admin dashboard can be previewed.

Rows are flagged is_demo and the dashboard shows a "Demo data" badge while any are in range.

    python -m scripts.seed_dashboard_demo            # add ~120 days of demo traffic
    python -m scripts.seed_dashboard_demo --clear    # remove all demo rows
"""

import argparse
import math
import random
import uuid
from datetime import UTC, datetime, timedelta

import dotenv
from backend.analytics.usage_store import UsageStore
from backend.databases.pgvector import PgVectorConnection

# made up prices for the demo chat model, USD per 1M tokens, so cost charts have something to show
_DEMO_CHAT_MODEL = ("demo/chat-model", 0.10, 0.40)
_EMBEDDING_MODEL = ("openai/text-embedding-3-small", 0.02, 0.0)
_EMBEDDING_CALLS_PER_REQUEST = 3  # one per vector store table


def _clear(conn) -> int:
    with conn.transaction():
        deleted = conn.execute("DELETE FROM usage_requests WHERE is_demo").rowcount
    return deleted


def _seed(conn, days: int, max_daily_users: int, rng: random.Random) -> int:
    now = datetime.now(UTC)
    user_pool = [f"demo-user-{i}" for i in range(max_daily_users * 6)]
    requests, calls = [], []

    for day in range(days, 0, -1):
        day_start = (now - timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        growth = 0.35 + 0.65 * (1 - day / days)  # traffic grows over the period
        weekday = 0.6 if day_start.weekday() >= 5 else 1.0  # quieter weekends
        daily_users = max(1, int(max_daily_users * growth * weekday * rng.uniform(0.8, 1.2)))
        # a slow provider day every few weeks shows up as a latency and error spike
        incident = rng.random() < 0.05

        for user in rng.sample(user_pool[: int(len(user_pool) * growth) or 1], daily_users):
            for _ in range(rng.choices([1, 2, 3], weights=[70, 22, 8])[0]):
                session = f"demo-session-{uuid.uuid4().hex[:12]}"
                started = day_start + timedelta(seconds=rng.uniform(6 * 3600, 22 * 3600))
                for _ in range(max(1, round(rng.lognormvariate(1.0, 0.6)))):
                    started += timedelta(seconds=rng.uniform(20, 240))
                    if started >= now:
                        break
                    _add_request(requests, calls, user, session, started, incident, rng)

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
    return len(requests)


def _add_request(requests: list, calls: list, user: str, session: str, started, incident: bool, rng) -> None:
    request_id = uuid.uuid4()
    roll = rng.random()
    failure_rate = 0.12 if incident else 0.015
    if roll < failure_rate:
        status, error = rng.choice([("rate_limited", "TooManyRequestsResponseError"), ("error", "RuntimeError")])
    elif roll < failure_rate + 0.04:
        status, error = "empty", None
    else:
        status, error = "ok", None

    model, embed_in, _ = _EMBEDDING_MODEL
    for _ in range(_EMBEDDING_CALLS_PER_REQUEST):
        tokens = rng.randint(8, 30)
        calls.append((request_id, started, "embedding", model, tokens, 0, True, tokens * embed_in / 1e6, 40, True))

    chat_latency = int(rng.lognormvariate(math.log(2_400 if incident else 1_400), 0.45))
    if status != "error":
        model, price_in, price_out = _DEMO_CHAT_MODEL
        tokens_in, tokens_out = rng.randint(1_800, 4_200), rng.randint(60, 320)
        cost = (tokens_in * price_in + tokens_out * price_out) / 1e6
        if status == "rate_limited":
            tokens_in = tokens_out = 0
            cost = 0
        calls.append(
            (
                request_id,
                started,
                "chat",
                model,
                tokens_in,
                tokens_out,
                False,
                cost,
                chat_latency,
                status != "rate_limited",
            )
        )

    latency = chat_latency + rng.randint(150, 600)
    requests.append((request_id, user, session if rng.random() > 0.02 else None, started, latency, status, error))


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
            print(f"Removed {_clear(conn)} demo requests.")
            return
        created = _seed(conn, args.days, args.users, random.Random(args.seed))
        print(f"Added {created} demo requests over {args.days} days. Remove them with --clear.")


if __name__ == "__main__":
    main()
