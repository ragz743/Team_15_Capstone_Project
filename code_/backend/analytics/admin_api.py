"""Admin only HTTP endpoints serving the usage dashboard."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated, Any, Literal

from backend.analytics.usage_store import UsageStore
from fastapi import APIRouter, Depends, Header, HTTPException, Query

logger = logging.getLogger("awn.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}

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
    range: Annotated[Literal["7d", "30d", "90d", "12m"], Query()] = "30d",
) -> dict[str, Any]:
    """Return cost, user, and performance metrics for the selected range."""
    try:
        return store.metrics(_RANGE_DAYS[range], os.getenv("AWN_DASHBOARD_TIMEZONE", _DEFAULT_TIMEZONE))
    except Exception as exc:
        logger.exception("Failed to compute dashboard metrics")
        raise HTTPException(status_code=503, detail="Usage metrics could not be loaded.") from exc
