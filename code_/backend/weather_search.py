"""Parameterized predicates for the three supported weather indexes."""

import json

from backend.weather_query import WeatherQuery

TIMESTAMP_KEYS = {"daily_index": "date", "live_index": "timestamp", "forecast_index": "timestamp"}
FILTERABLE_KEYS = frozenset({"station", "county", "state", "id"})


def _date_predicate(table: str) -> str:
    if table != "forecast_index":
        field = "metadata->>'date'" if table == "daily_index" else "left(metadata->>'timestamp', 10)"
        return f"{field} >= %s AND {field} <= %s"
    dates = (
        "jsonb_array_elements_text(CASE WHEN jsonb_typeof(metadata->'dates') = 'array' "
        "THEN metadata->'dates' ELSE COALESCE((SELECT jsonb_agg(m[1]) FROM "
        r"regexp_matches(document, '\|[ ]*([0-9]{4}-[0-9]{2}-[0-9]{2})[ T]', 'g') m), "
        "'[]'::jsonb) END) AS forecast_date"
    )
    return f"EXISTS (SELECT 1 FROM {dates} WHERE forecast_date >= %s AND forecast_date <= %s)"


def search_predicates(
    table: str,
    selection: WeatherQuery | None,
    metadata_filter: dict | None,
    staleness_days: int | None,
) -> tuple[str, list]:
    """Combine source and date restrictions before vector ranking or limits."""
    clauses, values = [], []
    if selection is not None:
        clauses.extend(["metadata->>'id' = ANY(%s)", _date_predicate(table)])
        values.extend([list(selection.station_ids), selection.start.isoformat(), selection.end.isoformat()])
        if selection.county:
            clauses.append("lower(metadata->>'county') = %s")
            values.append(selection.county.lower())
    if metadata_filter:
        clauses.append("metadata @> %s::jsonb")
        values.append(json.dumps(metadata_filter))
    if staleness_days is not None:
        clauses.append("(metadata->>%s)::date >= CURRENT_DATE - (%s * INTERVAL '1 day')")
        values.extend([TIMESTAMP_KEYS[table], staleness_days])
    return (f"WHERE {' AND '.join(clauses)} " if clauses else ""), values
