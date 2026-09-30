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
        bounded_query(query, "station1", {"AIR_TEMP", "TSTAMP"})


def test_aggregate_keeps_date_bounds_and_receives_output_limit():
    """Validate a useful weather aggregation without rewriting its period."""
    sql = bounded_query(
        "SELECT MIN(TSTAMP) AS source_start, MAX(TSTAMP) AS source_end, AVG(AIR_TEMP) AS average "
        "FROM station1 WHERE TSTAMP >= '2026-09-01' AND TSTAMP < '2026-09-08'",
        "station1",
        {"TSTAMP", "AIR_TEMP"},
    )
    assert "AVG(AIR_TEMP)" in sql and "'2026-09-08'" in sql and sql.endswith("LIMIT 200")


def test_forecast_latest_run_subquery_is_supported():
    """A forecast may read its own table to select the most recent model run."""
    sql = bounded_query(
        "SELECT Forecast_time, AIR_TEMP FROM fcst_1_2026 "
        "WHERE Init_time=(SELECT MAX(Init_time) FROM fcst_1_2026) LIMIT 24",
        "fcst_1_2026",
        {"Forecast_time", "Init_time", "AIR_TEMP"},
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
