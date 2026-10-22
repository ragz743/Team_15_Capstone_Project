"""Admin only HTTP endpoints serving the usage dashboard."""

from __future__ import annotations

import csv
import hmac
import io
import logging
import os
from typing import Annotated, Any, Literal

from backend.analytics.usage_store import UsageStore, UserSort
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger("awn.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}
RangeKey = Literal["7d", "30d", "90d", "12m"]

# the CSV export lists every user; this only guards against runaway responses
_CSV_MAX_USERS = 100_000
_CSV_COLUMNS = (
    "user_id",
    "requests",
    "sessions",
    "llm_calls",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "cost_share",
    "avg_cost_per_request",
    "first_seen",
    "last_seen",
)

# Dashboard dates are bucketed in AgWeatherNet's local time unless overridden.
_DEFAULT_TIMEZONE = "America/Los_Angeles"

_usage_store: UsageStore | None = None


def set_usage_store(store: UsageStore | None) -> None:
    """Register the store the admin endpoints read from, called at API startup."""
    global _usage_store
    _usage_store = store


def get_usage_store() -> UsageStore:
    """Return the registered usage store, or 503 when analytics is not available."""
    if _usage_store is None:
        raise HTTPException(status_code=503, detail="Usage analytics is not available.")
    return _usage_store


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Allow the request only with `Authorization: Bearer <AWN_ADMIN_TOKEN>`."""
    expected = os.getenv("AWN_ADMIN_TOKEN")
    if not expected:
        # fail closed: an unset token must never mean "no authentication"
        raise HTTPException(status_code=503, detail="The admin dashboard is not configured.")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin token.", headers={"WWW-Authenticate": "Bearer"})


@router.get("/metrics", dependencies=[Depends(require_admin)])
def metrics(
    store: Annotated[UsageStore, Depends(get_usage_store)],
    range: Annotated[RangeKey, Query()] = "30d",
) -> dict[str, Any]:
    """Return cost, user, and performance metrics for the selected range."""
    try:
        return store.metrics(_RANGE_DAYS[range], _timezone())
    except Exception as exc:
        logger.exception("Failed to compute dashboard metrics")
        raise HTTPException(status_code=503, detail="Usage metrics could not be loaded.") from exc


# search and sort options shared by the JSON and CSV endpoints
SearchParam = Annotated[str | None, Query(max_length=64, description="Show users whose id contains this text")]
SortParam = Annotated[UserSort, Query(description="Column to sort by")]
OrderParam = Annotated[Literal["asc", "desc"], Query()]


@router.get("/users", dependencies=[Depends(require_admin)])
def users(
    store: Annotated[UsageStore, Depends(get_usage_store)],
    range: Annotated[RangeKey, Query()] = "30d",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: SearchParam = None,
    sort: SortParam = "cost_usd",
    order: OrderParam = "desc",
) -> dict[str, Any]:
    """Return each user's LLM usage and cost for the range, one page at a time, filtered and sorted."""
    try:
        return store.users(
            _RANGE_DAYS[range],
            _timezone(),
            limit=limit,
            offset=offset,
            search=search,
            sort=sort,
            descending=order == "desc",
        )
    except Exception as exc:
        logger.exception("Failed to load per user costs")
        raise HTTPException(status_code=503, detail="Per user costs could not be loaded.") from exc


@router.get("/users.csv", dependencies=[Depends(require_admin)])
def users_csv(
    store: Annotated[UsageStore, Depends(get_usage_store)],
    range: Annotated[RangeKey, Query()] = "30d",
    search: SearchParam = None,
    sort: SortParam = "cost_usd",
    order: OrderParam = "desc",
) -> Response:
    """Download the users shown in the table (same search and sort, every page) as CSV."""
    try:
        result = store.users(
            _RANGE_DAYS[range],
            _timezone(),
            limit=_CSV_MAX_USERS,
            search=search,
            sort=sort,
            descending=order == "desc",
        )
    except Exception as exc:
        logger.exception("Failed to export per user costs")
        raise HTTPException(status_code=503, detail="Per user costs could not be loaded.") from exc

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(result["users"])
    if result["unidentified"] and not search:
        writer.writerow({**result["unidentified"], "user_id": "(unidentified)"})
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="awn-llm-cost-by-user-{range}.csv"'},
    )


def _timezone() -> str:
    return os.getenv("AWN_DASHBOARD_TIMEZONE", _DEFAULT_TIMEZONE)
