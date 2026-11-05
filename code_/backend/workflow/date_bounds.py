"""Prove that generated weather reads have a finite period using the SQL tree."""

from datetime import datetime, timedelta

from mysql.connector.errors import ProgrammingError
from sqlglot import exp

Bounds = tuple[datetime | None, datetime | None]
_COMPARISONS = {exp.EQ: "eq", exp.GT: "gt", exp.GTE: "gte", exp.LT: "lt", exp.LTE: "lte"}
_REVERSED = {"eq": "eq", "gt": "lt", "gte": "lte", "lt": "gt", "lte": "gte"}


def validate_date_bounds(statement: exp.Select, date_column: str, max_days: int | None) -> None:
    """Require bounds on every weather read, including nested aggregates."""
    for query in statement.find_all(exp.Select):
        table = _source_table(query)
        if date_column.casefold() == "forecast_time" and _latest_forecast_run(query, table):
            continue
        where = query.args.get("where")
        start, end = _predicate_bounds(where.this, date_column, table) if where else (None, None)
        if start is None or end is None:
            raise ProgrammingError(f"Bound {date_column} with explicit ISO date literals on both sides or an equality.")
        if start >= end:
            raise ProgrammingError("The weather date range must be nonempty and ordered.")
        if max_days is not None and end - start > timedelta(days=max_days):
            raise ProgrammingError(f"Historical date ranges cannot exceed {max_days} days.")


def _source_table(query: exp.Select) -> exp.Table:
    source = query.args.get("from_")
    if source is None or not isinstance(source.this, exp.Table):
        raise ProgrammingError("Read directly from the selected station table.")
    return source.this


def _is_column(node: exp.Expr, name: str, table: exp.Table) -> bool:
    return (
        isinstance(node, exp.Column)
        and node.name.casefold() == name.casefold()
        and (not node.table or node.table.casefold() == table.alias_or_name.casefold())
    )


def _latest_forecast_run(query: exp.Select, table: exp.Table) -> bool:
    """Allow only the scalar MAX(Init_time) lookup used to select a forecast run."""
    if any(value for key, value in query.args.items() if key not in {"expressions", "from_"}):
        return False
    if len(query.expressions) != 1 or not isinstance(query.expressions[0], exp.Max):
        return False
    if not _is_column(query.expressions[0].this, "Init_time", table):
        return False
    subquery = query.parent
    comparison = subquery.parent if isinstance(subquery, exp.Subquery) else None
    if not isinstance(comparison, exp.EQ):
        return False
    other = comparison.expression if comparison.this is subquery else comparison.this
    outer = comparison.find_ancestor(exp.Select)
    return outer is not None and _is_column(other, "Init_time", _source_table(outer))


def _predicate_bounds(node: exp.Expr, column: str, table: exp.Table) -> Bounds:
    node = node.unnest()
    if isinstance(node, (exp.And, exp.Or)):
        return _combine_bounds(
            _predicate_bounds(node.this, column, table),
            _predicate_bounds(node.expression, column, table),
            union=isinstance(node, exp.Or),
        )
    if isinstance(node, exp.Between):
        return _combine_bounds(
            _comparison_bounds(node.this, node.args["low"], "gte", column, table),
            _comparison_bounds(node.this, node.args["high"], "lte", column, table),
        )
    operator = _COMPARISONS.get(type(node))
    if operator is not None:
        return _comparison_bounds(node.this, node.expression, operator, column, table)
    return None, None


def _combine_bounds(left: Bounds, right: Bounds, *, union: bool = False) -> Bounds:
    starts = [value for value in (left[0], right[0]) if value is not None]
    ends = [value for value in (left[1], right[1]) if value is not None]
    if union:
        return min(starts) if len(starts) == 2 else None, max(ends) if len(ends) == 2 else None
    return max(starts, default=None), min(ends, default=None)


def _date_resolution(node: exp.Expr, column: str, table: exp.Table) -> timedelta | None:
    node = node.unnest()
    if _is_column(node, column, table):
        return timedelta(days=1) if column.casefold() == "juldate" else timedelta(microseconds=1)
    if isinstance(node, (exp.Date, exp.TsOrDsToDate)) and _is_column(node.this, column, table):
        return timedelta(days=1)
    if isinstance(node, exp.Cast) and node.args["to"].this == exp.DataType.Type.DATE:
        if _is_column(node.this, column, table):
            return timedelta(days=1)
    return None


def _comparison_bounds(left: exp.Expr, right: exp.Expr, operator: str, column: str, table: exp.Table) -> Bounds:
    step = _date_resolution(left, column, table)
    if step is None:
        step = _date_resolution(right, column, table)
        left, right, operator = right, left, _REVERSED[operator]
    if step is None:
        return None, None
    value = _date_literal(right, date_only=step == timedelta(days=1))
    try:
        if operator == "eq":
            return value, value + step
        if operator in {"gt", "gte"}:
            return value + step if operator == "gt" else value, None
        return None, value + step if operator == "lte" else value
    except OverflowError as exc:
        raise ProgrammingError("The weather date is outside the supported range.") from exc


def _date_literal(node: exp.Expr, *, date_only: bool) -> datetime:
    if not isinstance(node, exp.Literal) or not node.is_string:
        raise ProgrammingError("Use explicit ISO date literals derived from the supplied reference time.")
    text = node.this
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ProgrammingError("Use an ISO date or timestamp literal for weather bounds.") from exc
    if value.tzinfo is not None or text[:10] != value.date().isoformat() or (date_only and len(text) != 10):
        raise ProgrammingError("Use YYYY-MM-DD dates or local ISO timestamps for weather bounds.")
    return value
