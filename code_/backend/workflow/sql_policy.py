"""Restrict generated queries to bounded reads of one station table."""

from backend.workflow.date_bounds import validate_date_bounds
from mysql.connector.errors import ProgrammingError
from sqlglot import exp, parse
from sqlglot.errors import ParseError

MAX_ROWS = 200
UNAVAILABLE_QUERY = "SELECT NULL AS unavailable"
_FUNCTIONS = {
    "ABS",
    "AND",
    "OR",
    "AVG",
    "CAST",
    "CEIL",
    "COALESCE",
    "COUNT",
    "DATE",
    "DATE_ADD",
    "DATE_SUB",
    "DATEDIFF",
    "DAY",
    "EXTRACT",
    "FLOOR",
    "GREATEST",
    "LEAST",
    "MAX",
    "MIN",
    "MONTH",
    "NULLIF",
    "ROUND",
    "SUM",
    "TIME",
    "TIMESTAMPDIFF",
    "TS_OR_DS_TO_DATE",
    "YEAR",
}


def measurement_unit(column: str) -> str | None:
    """Expose weather measurements while excluding operational metadata."""
    name = column.upper()
    if (
        name.endswith("_TIME")
        or name == "PANEL_TEMP"
        or any(part in name for part in ("_QA_", "_MODIF", "_REASON", "_METHOD"))
    ):
        return None
    if "TEMP" in name or "DEWPOINT" in name:
        return "F"
    if "HUMID" in name:
        return "%"
    if "PRECIP" in name:
        return "inches"
    if "WIND_SP" in name or "WIND_SPEED" in name:
        return "mph"
    if "WIND_DIR" in name:
        return "degrees"
    if name == "SOLAR_RAD":
        return "W/m²"
    return None


def bounded_query(
    query: str, table_name: str, columns: set[str] | None = None, *, date_column: str, max_days: int | None = None
) -> str:
    """Validate the syntax tree before adding an output row limit."""
    statement = _parse_select(query)
    if statement == exp.select(exp.alias_(exp.Null(), "unavailable")):
        return UNAVAILABLE_QUERY
    _validate_read(statement, table_name, columns)
    validate_date_bounds(statement, date_column, max_days)
    return _limit_result(statement)


def _parse_select(query: str) -> exp.Select:
    if len(query) > 12000:
        raise ProgrammingError("The generated query is too long.")
    try:
        statements = parse(query, read="mysql")
    except ParseError as exc:
        raise ProgrammingError("Return one valid SELECT statement.") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ProgrammingError("Only one SELECT statement is supported.")
    return statements[0]


def _validate_read(statement: exp.Select, table_name: str, columns: set[str] | None) -> None:
    forbidden = (
        exp.Into,
        exp.Lock,
        exp.Join,
        exp.Union,
        exp.With,
        exp.Command,
        exp.Parameter,
        exp.SessionParameter,
        exp.Placeholder,
    )
    if any(isinstance(node, forbidden) or node.comments for node in statement.walk()):
        raise ProgrammingError("This query uses unsupported SQL clauses.")
    tables = list(statement.find_all(exp.Table))
    if not tables or any(t.name.casefold() != table_name.casefold() or t.db or t.catalog for t in tables):
        raise ProgrammingError("Only the selected station table may be read.")
    for function in statement.find_all(exp.Func):
        if function.sql_name() not in _FUNCTIONS:
            raise ProgrammingError("Use supported functions and explicit dates, never the database clock.")
    for star in statement.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise ProgrammingError("Select named measurement columns rather than all columns.")
    if columns is not None:
        allowed = {column.casefold() for column in columns}
        aliases = {alias.alias.casefold() for alias in statement.find_all(exp.Alias)}
        for column in statement.find_all(exp.Column):
            is_order_alias = isinstance(column.parent, exp.Ordered) and column.name.casefold() in aliases
            if column.name.casefold() not in allowed and not is_order_alias:
                raise ProgrammingError("Select only the measurement and date columns in the supplied schema.")


def _limit_result(statement: exp.Select) -> str:
    if statement.args.get("offset") is not None:
        raise ProgrammingError("Offsets are not supported.")
    limit = statement.args.get("limit")
    if limit is not None:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int or not 1 <= int(value.this) <= MAX_ROWS:
            raise ProgrammingError(f"LIMIT must be between 1 and {MAX_ROWS}.")
    else:
        statement = statement.limit(MAX_ROWS)
    return statement.sql(dialect="mysql")
