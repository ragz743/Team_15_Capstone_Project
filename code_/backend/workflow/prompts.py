"""SQL generation instructions shared by the weather query nodes."""

SQL_QUERY_PROMPT = """You write one read-only MySQL query for AgWeatherNet.
Query topic: {query_type}
Reference time in Washington: {reference_time}
User request:
{query_request}

The only allowed table is `{table_name}` for station ID {station_id}.
Station schema:
{schema_context}

Return only one SQL SELECT statement written for MariaDB.
The SQL statement shall contain no markdown fences,
explanation, comments, or semicolon-separated statements.
Do not use any table other than `{table_name}`. Use SQL literals for dates
and numeric values. Do not emit parameter placeholders. Select named columns,
never SELECT *. Include the observation or forecast date in returned rows.
For aggregates include MIN(date_column) AS source_start and
MAX(date_column) AS source_end. A high or low for a whole day or period
must aggregate ALL matching rows, without GROUP BY individual timestamps
or selecting a single arbitrary hour. For example a forecast daily high
uses SELECT MIN(Forecast_time) AS source_start, MAX(Forecast_time) AS source_end,
MAX(AIR_TEMP) AS high_temp FROM the_allowed_table WHERE the_date_range
AND Init_time = (SELECT MAX(Init_time) FROM the_allowed_table).
Use AVG_AIR_TEMP for average daily temperature,
MAX_AIR_TEMP for daily highs and MIN_AIR_TEMP for daily lows when available.
Never substitute an average for a high or low. Column comments give units.
If the requested measurement is absent from the schema, return
SELECT NULL AS unavailable FROM `{table_name}` LIMIT 1.
Restrict historical date ranges to at most 366 days. For current weather,
select the latest record within the requested day. For forecasts select
the latest Init_time and the requested Forecast_time period, never all runs.
Include an appropriate WHERE date range and LIMIT no greater than {max_rows}.
Return the SQL only.
"""
