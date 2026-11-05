"""Bounded history search predicates with explicit owner and acceptance cutoffs."""

from datetime import datetime
from uuid import UUID


def history_search(
    owner: UUID,
    before: datetime,
    *,
    target: UUID | None,
    terms: list[str],
    start: datetime | None,
    end: datetime | None,
) -> tuple[bytes, dict]:
    """Filter before sorting without materializing every message owned by the browser."""
    clauses = ["c.owner_id = %(owner)s", "t.requested_at < %(before)s"]
    parameters = {"owner": owner, "before": before, "target": target, "terms": terms, "start": start, "end": end}
    if target is not None:
        clauses.append("c.id = %(target)s")
    if start is not None:
        clauses.append("t.requested_at >= %(start)s")
    if end is not None:
        clauses.append("t.requested_at < %(end)s")
    if terms:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(%(terms)s::text[]) AS term WHERE "
            "strpos(lower(t.user_content), lower(term)) > 0 OR "
            "(t.completed_at <= %(before)s AND strpos(lower(t.assistant_content), lower(term)) > 0))"
        )
    query = (
        "SELECT c.id AS conversation_id, c.title, t.ordinal, t.user_content, t.requested_at, "
        "CASE WHEN t.completed_at <= %(before)s THEN t.assistant_content END AS assistant_content, "
        "CASE WHEN t.completed_at <= %(before)s THEN t.context END AS context "
        "FROM conversations c JOIN conversation_turns t ON t.conversation_id = c.id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY t.requested_at DESC, c.id DESC, t.ordinal DESC LIMIT 13"
    )
    return query.encode(), parameters
