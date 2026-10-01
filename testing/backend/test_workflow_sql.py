"""Generated SQL stays within the selected station and public measurement schema."""

import pytest
from backend.workflow.sql_policy import bounded_query, measurement_unit
from mysql.connector.errors import ProgrammingError


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM station1",
        "SELECT AIR_TEMP FROM station1; DROP TABLE station1",
        "SELECT AIR_TEMP FROM station2",
        "SELECT AIR_TEMP FROM other.station1",
        "SELECT AIR_TEMP FROM station1 UNION SELECT AIR_TEMP FROM station2",
        "SELECT AIR_TEMP INTO OUTFILE '/tmp/weather' FROM station1",
        "SELECT SLEEP(20) FROM station1",
        "SELECT LOAD_FILE('/etc/passwd') FROM station1",
        "SELECT @@version FROM station1",
        "SELECT * FROM station1",
        "SELECT AIR_TEMP_MODIFIED_BY FROM station1",
        "SELECT AIR_TEMP_MODIFIED_BY AS AIR_TEMP_MODIFIED_BY FROM station1",
        "SELECT AIR_TEMP FROM station1 FOR UPDATE",
        "SELECT AIR_TEMP FROM station1 LIMIT 201",
        "SELECT AIR_TEMP FROM station1 LIMIT 1 OFFSET 200",
        "SELECT AIR_TEMP FROM station1 WHERE TSTAMP >= %s",
        "SELECT AIR_TEMP FROM station1 /* comment */",
    ],
)
def test_rejects_queries_outside_station_read_contract(query):
    """Refuse forbidden operations before a database cursor is opened."""
    with pytest.raises(ProgrammingError):
        bounded_query(query, "station1", {"AIR_TEMP", "TSTAMP"}, date_column="TSTAMP")


def test_aggregate_keeps_date_bounds_and_receives_output_limit():
    """Validate a useful weather aggregation without rewriting its period."""
    sql = bounded_query(
        "SELECT MIN(TSTAMP) AS source_start, MAX(TSTAMP) AS source_end, AVG(AIR_TEMP) AS average "
        "FROM station1 WHERE TSTAMP >= '2026-09-01' AND TSTAMP < '2026-09-08'",
        "station1",
        {"TSTAMP", "AIR_TEMP"},
        date_column="TSTAMP",
    )
    assert "AVG(AIR_TEMP)" in sql and "'2026-09-08'" in sql and sql.endswith("LIMIT 200")


def test_forecast_latest_run_subquery_is_supported():
    """A forecast may read its own table to select the most recent model run."""
    sql = bounded_query(
        "SELECT Forecast_time, AIR_TEMP FROM fcst_1_2026 "
        "WHERE Forecast_time >= '2026-09-30' AND Forecast_time < '2026-10-01' "
        "AND Init_time=(SELECT MAX(Init_time) FROM fcst_1_2026) LIMIT 24",
        "fcst_1_2026",
        {"Forecast_time", "Init_time", "AIR_TEMP"},
        date_column="Forecast_time",
    )
    assert "MAX(Init_time)" in sql and sql.endswith("LIMIT 24")


def test_operational_columns_are_not_weather_measurements():
    """Keep staff and modification metadata out of model prompts and query results."""
    assert measurement_unit("AIR_TEMP_MODIFIED_BY") is None
    assert measurement_unit("AIR_TEMP_QA_FLAG") is None
    assert measurement_unit("MAX_TEMP_TIME") is None
    assert measurement_unit("PANEL_TEMP") is None
    assert measurement_unit("SUM_SOLAR_RAD") is None
    assert measurement_unit("MIN_AIR_TEMP") == "F"
    assert measurement_unit("SUM_PRECIP") == "inches"


@pytest.mark.parametrize(
    "predicate",
    [
        "",
        "WHERE JULDATE >= '2026-09-01'",
        "WHERE JULDATE < '2026-10-01'",
        "WHERE JULDATE >= '2000-01-01' AND JULDATE < '2026-10-01'",
        "WHERE JULDATE BETWEEN '2024-01-01' AND '2025-01-01'",
        "WHERE JULDATE = '2026-09-29' OR 1 = 1",
        "WHERE JULDATE = '2026-09-29' OR AVG_AIR_TEMP > 50",
        "WHERE JULDATE = '2024-01-01' OR JULDATE = '2026-09-29'",
        "WHERE JULDATE >= '2026-09-29' AND (JULDATE < '2026-09-30' OR 1 = 1)",
        "WHERE NOT JULDATE BETWEEN '2026-09-29' AND '2026-09-30'",
        "WHERE JULDATE >= '2026-10-01' AND JULDATE < '2026-09-01'",
        "WHERE JULDATE > '2026-09-29' AND JULDATE <= '2026-09-29'",
        "WHERE JULDATE = 'yesterday'",
        "WHERE JULDATE = '2026-02-30'",
        "WHERE JULDATE = '9999-12-31'",
        "WHERE JULDATE = 20260929",
        "WHERE JULDATE = '2026-09-29T00:00:00+00:00'",
        "WHERE JULDATE = '2026-09-29 12:00:00'",
        "WHERE YEAR(JULDATE) = 2026",
        "WHERE INIT_TIME = '2026-09-29'",
        "WHERE other.JULDATE = '2026-09-29'",
    ],
)
def test_historical_queries_require_a_real_bounded_period(predicate):
    """Reject missing, bypassed, invalid or excessive periods before execution."""
    with pytest.raises(ProgrammingError):
        bounded_query(
            f"SELECT AVG(AVG_AIR_TEMP) FROM station1daily {predicate}",
            "station1daily",
            {"AVG_AIR_TEMP", "JULDATE", "INIT_TIME"},
            date_column="JULDATE",
            max_days=366,
        )


@pytest.mark.parametrize(
    "predicate",
    [
        "JULDATE = '2026-09-29'",
        "'2026-09-29' = JULDATE",
        "JULDATE >= '2024-01-01' AND JULDATE < '2025-01-01'",
        "JULDATE BETWEEN '2024-01-01' AND '2024-12-31'",
        "JULDATE > '2023-12-31' AND JULDATE <= '2024-12-31'",
        "'2024-01-01' <= JULDATE AND '2025-01-01' > JULDATE",
        "(JULDATE = '2026-09-29' OR JULDATE = '2026-09-30')",
        "JULDATE = '2026-09-29' AND (AVG_AIR_TEMP > 50 OR AVG_AIR_TEMP < 30)",
    ],
)
def test_date_bounds_allow_day_queries_leap_years_and_bounded_boolean_filters(predicate):
    """Keep supported periods without changing the generated SQL's meaning."""
    query = bounded_query(
        f"SELECT AVG(AVG_AIR_TEMP) FROM station1daily WHERE {predicate}",
        "station1daily",
        {"AVG_AIR_TEMP", "JULDATE"},
        date_column="JULDATE",
        max_days=366,
    )
    assert query.endswith("LIMIT 200")


@pytest.mark.parametrize("column", ["TSTAMP", "Forecast_time"])
@pytest.mark.parametrize("expression", ["{column}", "DATE({column})", "CAST({column} AS DATE)"])
def test_timestamp_columns_and_date_wrappers_support_absolute_periods(column, expression):
    """Date expressions still refer to the selected source's applicable time field."""
    predicate = expression.format(column=f"s.{column}")
    query = bounded_query(
        f"SELECT AIR_TEMP FROM station1 s WHERE {predicate} >= '2026-09-29' AND {predicate} < '2026-09-30'",
        "station1",
        {column, "AIR_TEMP"},
        date_column=column,
    )
    assert "2026-09-29" in query


@pytest.mark.parametrize(
    "clock",
    [
        "CURRENT_DATE",
        "CURRENT_DATE()",
        "CURDATE()",
        "CURRENT_TIMESTAMP",
        "CURRENT_TIMESTAMP()",
        "NOW()",
        "UTC_TIMESTAMP()",
        "UTC_DATE()",
        "SYSDATE()",
        "LOCALTIME",
        "LOCALTIMESTAMP()",
    ],
)
def test_database_clock_functions_are_rejected_even_inside_a_bounded_query(clock):
    """A saved request cannot silently switch to a later database date."""
    with pytest.raises(ProgrammingError):
        bounded_query(
            f"SELECT AIR_TEMP, {clock} FROM station1 WHERE TSTAMP >= '2026-09-29' AND TSTAMP < '2026-09-30'",
            "station1",
            {"AIR_TEMP", "TSTAMP"},
            date_column="TSTAMP",
        )


@pytest.mark.parametrize("clock", ["CURRENT_DATE", "CURDATE()", "CURRENT_TIMESTAMP()"])
def test_database_clock_functions_are_rejected_in_date_predicates(clock):
    """Reject the original retry drift examples before a database cursor opens."""
    with pytest.raises(ProgrammingError):
        bounded_query(
            f"SELECT AVG(AIR_TEMP) FROM station1 WHERE TSTAMP >= {clock}",
            "station1",
            {"AIR_TEMP", "TSTAMP"},
            date_column="TSTAMP",
        )


@pytest.mark.parametrize(
    "subquery",
    ["SELECT AVG(AIR_TEMP) FROM station1", "SELECT MAX(TSTAMP) FROM station1"],
)
def test_outer_date_bounds_do_not_exempt_nested_weather_reads(subquery):
    """A bounded outer query cannot hide an all-time nested aggregate."""
    with pytest.raises(ProgrammingError):
        bounded_query(
            f"SELECT AIR_TEMP, ({subquery}) FROM station1 WHERE TSTAMP >= '2026-09-29' AND TSTAMP < '2026-09-30'",
            "station1",
            {"AIR_TEMP", "TSTAMP"},
            date_column="TSTAMP",
        )


def test_bounded_nested_weather_read_is_supported():
    """Both sides of a comparison can read evidence from a bounded period."""
    sql = bounded_query(
        "SELECT AIR_TEMP FROM station1 WHERE TSTAMP >= '2026-09-29' AND TSTAMP < '2026-09-30' "
        "AND AIR_TEMP > (SELECT AVG(AIR_TEMP) FROM station1 "
        "WHERE TSTAMP >= '2026-09-29' AND TSTAMP < '2026-09-30')",
        "station1",
        {"AIR_TEMP", "TSTAMP"},
        date_column="TSTAMP",
    )
    assert "AVG(AIR_TEMP)" in sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT AIR_TEMP FROM fcst_1_2026 WHERE Init_time=(SELECT MAX(Init_time) FROM fcst_1_2026)",
        "SELECT AIR_TEMP FROM fcst_1_2026 WHERE Forecast_time='2026-10-01' "
        "AND Init_time=(SELECT MAX(Init_time) FROM fcst_1_2026 WHERE AIR_TEMP > 50)",
        "SELECT AIR_TEMP, (SELECT MAX(Init_time) FROM fcst_1_2026) FROM fcst_1_2026 WHERE Forecast_time='2026-10-01'",
    ],
)
def test_forecast_exception_is_limited_to_the_latest_run_lookup(query):
    """A run selection never substitutes for the requested forecast period."""
    with pytest.raises(ProgrammingError):
        bounded_query(query, "fcst_1_2026", {"AIR_TEMP", "Forecast_time", "Init_time"}, date_column="Forecast_time")


def test_missing_measurement_sentinel_is_a_constant_without_a_table_read():
    """Only the exact no-data marker can omit date bounds and a station table."""
    assert bounded_query("SELECT NULL AS unavailable", "station1", date_column="TSTAMP") == "SELECT NULL AS unavailable"
    for query in ["SELECT NULL AS unavailable FROM station1 LIMIT 1", "SELECT 72 AS unavailable"]:
        with pytest.raises(ProgrammingError):
            bounded_query(query, "station1", date_column="TSTAMP")
