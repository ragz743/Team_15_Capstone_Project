"""Opt in checks for the station directory using a disposable database schema."""

import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

import psycopg
import pytest
from backend.databases.pgvector import PgVectorConnection
from backend.station_catalog import StationCatalog
from backend.weather_query import QueryClarificationError
from psycopg import sql
from psycopg.types.json import Jsonb
from weather_fixtures import POINT

pytestmark = pytest.mark.skipif(os.getenv("RUN_PG_TESTS") != "1", reason="Set RUN_PG_TESTS=1 for PostgreSQL checks")
TABLES = ("daily_index", "live_index", "forecast_index")


def _metadata(**changes):
    return {
        "id": "1",
        "station": "Pullman",
        "county": "Whitman",
        "state": "WA",
        "latitude": "46.731",
        "longitude": "117.181",
        **changes,
    }


def _insert(connection, table="daily_index", **changes):
    return connection.execute(
        sql.SQL("INSERT INTO {} (metadata) VALUES (%s) RETURNING id").format(sql.Identifier(table)),
        (Jsonb(_metadata(**changes)),),
    ).fetchone()[0]


def _seed_weather_history(connection):
    """Give 500 stations two years of daily records and one current record per other index."""
    for table in TABLES:
        last_day = 729 if table == "daily_index" else 0
        connection.execute(
            sql.SQL("""
                INSERT INTO {} (metadata)
                SELECT jsonb_build_object(
                    'id', n::text, 'station', 'Station ' || n, 'county', 'Test county', 'state', 'WA',
                    'latitude', (45.1 + ((n - 2) / 25) * 0.24)::text,
                    'longitude', (-124.9 + ((n - 2) %% 25) * 0.36)::text,
                    'date', (date '2024-01-01' + day)::text,
                    'timestamp', (date '2024-01-01' + day)::text || ' 12:00:00'
                )
                FROM generate_series(2, 501) n CROSS JOIN generate_series(0, %s) day
            """).format(sql.Identifier(table)),
            (last_day,),
        )


@pytest.fixture
def directory(request):
    """Roll back the schema, functions and records without touching application tables."""
    with psycopg.connect(
        host="127.0.0.1",
        port=int(os.getenv("PG_PORT", "5432")),
        dbname="vectorstore",
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        connect_timeout=3,
    ) as connection:
        schema = sql.Identifier("station_test_" + uuid4().hex)
        try:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
            connection.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(schema))
            for table in TABLES:
                connection.execute(
                    sql.SQL("CREATE TABLE {} (id serial PRIMARY KEY, metadata jsonb)").format(sql.Identifier(table))
                )
                connection.execute(sql.SQL("CREATE INDEX ON {} ((metadata->>'id'))").format(sql.Identifier(table)))
            _insert(connection)
            if getattr(request, "param", None) == "history":
                _seed_weather_history(connection)
            migration = Path(__file__).parents[2] / "deployment/migrations/002_station_directory.sql"
            body = migration.read_text().removeprefix("BEGIN;\n").removesuffix("\nCOMMIT;\n")
            connection.execute(body.encode())
            database = PgVectorConnection.__new__(PgVectorConnection)
            database.conn, database._query_lock = connection, Lock()
            yield connection, database
        finally:
            connection.rollback()


def test_backfill_creates_one_normalized_source(directory):
    """The first request can select an existing source without rebuilding metadata."""
    connection, database = directory
    station = StationCatalog(database).resolve(POINT)
    assert station.id == "1" and station.longitude == "-117.181"
    assert connection.execute("SELECT count(*) FROM indexed_stations").fetchone()[0] == 1


@pytest.mark.parametrize("table", TABLES)
def test_weather_writes_maintain_the_directory(directory, table):
    """Inserts, corrections and deletions become visible in the same transaction."""
    connection, database = directory
    record = _insert(connection, table, id="2", station="New source", latitude="46.73", longitude="-117.18")
    assert StationCatalog(database).resolve(POINT).id == "2"
    connection.execute(
        sql.SQL("UPDATE {} SET metadata = %s WHERE id = %s").format(sql.Identifier(table)),
        (Jsonb(_metadata(id="2", station="Corrected", latitude="46.73", longitude="-117.18")), record),
    )
    assert StationCatalog(database).resolve(POINT).name == "Corrected"
    connection.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table)), (record,))
    assert StationCatalog(database).resolve(POINT).id == "1"


def test_repeated_readings_do_not_rebuild_station_metadata(directory):
    """New dates and changed weather values keep the existing directory row."""
    connection, _ = directory
    original = connection.execute("SELECT ctid FROM indexed_stations WHERE station_id = '1'").fetchone()
    record = _insert(connection, date="2026-09-10", temperature=72)
    connection.execute(
        "UPDATE daily_index SET metadata = metadata || %s WHERE id = %s", (Jsonb({"temperature": 73}), record)
    )
    assert connection.execute("SELECT ctid FROM indexed_stations WHERE station_id = '1'").fetchone() == original


def test_bulk_changes_preserve_conflict_detection_and_recovery(directory):
    """Check the complete statement when several changed rows belong to one station."""
    connection, database = directory
    connection.execute(
        "INSERT INTO daily_index (metadata) VALUES (%s), (%s)",
        (Jsonb(_metadata(id="2")), Jsonb(_metadata(id="2", station="Other"))),
    )
    assert connection.execute("SELECT station_id FROM indexed_stations").fetchall() == [("1",)]
    connection.execute(
        "UPDATE daily_index SET metadata = %s WHERE metadata->>'id' = '2'",
        (Jsonb(_metadata(id="2", latitude="46.73", longitude="-117.18")),),
    )
    assert StationCatalog(database).resolve(POINT).id == "2"
    connection.execute("DELETE FROM daily_index WHERE metadata->>'id' = '2'")
    assert StationCatalog(database).resolve(POINT).id == "1"


@pytest.mark.parametrize("change", [{"station": "Other"}, {"county": "Other"}, {"latitude": "49.0"}])
def test_conflicts_are_excluded_and_recover_after_correction(directory, change):
    """Conflicts remain disqualifying even if the other coordinate is far outside the search box."""
    connection, database = directory
    record = _insert(connection, "live_index", **change)
    with pytest.raises(QueryClarificationError):
        StationCatalog(database).resolve(POINT)
    connection.execute("DELETE FROM live_index WHERE id = %s", (record,))
    assert StationCatalog(database).resolve(POINT).id == "1"


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": None},
        {"longitude": "NaN"},
        {"longitude": "invalid"},
        {"longitude": "0"},
        {"latitude": "1e1000"},
        {"state": "OR"},
        {"latitude": "90"},
        {"id": "invalid"},
        {"station": ""},
    ],
)
def test_invalid_sources_never_enter_the_directory(directory, change):
    """Bad metadata cannot break ingestion or become a selectable source."""
    connection, _ = directory
    _insert(connection, **{"id": "2", **change})
    assert connection.execute("SELECT station_id FROM indexed_stations").fetchall() == [("1",)]


def test_signed_and_unsigned_west_longitudes_share_one_identity(directory):
    """Equivalent longitude formats do not exclude a valid station."""
    connection, database = directory
    _insert(connection, "forecast_index", longitude="-117.181")
    assert StationCatalog(database).resolve(POINT).id == "1"


def test_requested_index_must_have_records(directory):
    """The directory cannot broaden retrieval to a station absent from the configured indexes."""
    connection, database = directory
    _insert(connection, "forecast_index", id="2", station="Forecast source", latitude="46.73", longitude="-117.18")
    assert StationCatalog(database).resolve(POINT).id == "2"
    assert StationCatalog(database, tables=("daily_index",)).resolve(POINT).id == "1"


def test_spherical_distance_and_radius_decide_the_selected_source(directory):
    """Raw distance in degrees and bounding box corners are not accepted as kilometer distance."""
    connection, database = directory
    connection.execute("DELETE FROM daily_index")
    _insert(connection, id="2", latitude="46.83", longitude="-117.18")
    _insert(connection, id="3", latitude="46.73", longitude="-117.06")
    assert StationCatalog(database).resolve(POINT).id == "3"
    with pytest.raises(QueryClarificationError):
        StationCatalog(database, radius_km=5).resolve(POINT)
    connection.execute("DELETE FROM daily_index")
    _insert(connection, latitude="47.13", longitude="-116.58")
    with pytest.raises(QueryClarificationError):
        StationCatalog(database).resolve(POINT)


def test_station_id_change_updates_both_directory_entries(directory):
    """A corrected identity cannot leave an orphaned source in the directory."""
    connection, database = directory
    connection.execute("UPDATE daily_index SET metadata = jsonb_set(metadata, '{id}', '\"2\"')")
    assert connection.execute("SELECT station_id FROM indexed_stations").fetchall() == [("2",)]
    assert StationCatalog(database).resolve(POINT).id == "2"


def test_tied_distances_have_a_stable_station_choice(directory):
    """Repeated lookups resolve equal distances by station ID."""
    connection, database = directory
    _insert(connection, id="2")
    assert StationCatalog(database).resolve(POINT).id == "1"


def test_query_plan_uses_geographic_index_without_loading_weather_metadata(directory):
    """An ordinary lookup prunes a large distant directory through its geographic index."""
    connection, database = directory
    connection.execute("""
        INSERT INTO indexed_stations (station_id, name, county, state, latitude, longitude)
        SELECT n::text, 'Distant', 'Other', 'WA', 45 + (n % 500) / 1000.0, -125 + (n % 300) / 1000.0
        FROM generate_series(2, 20001) n
    """)
    connection.execute("ANALYZE indexed_stations")
    from backend.station_catalog import _nearest_station_query, _search_bounds

    query = _nearest_station_query(TABLES)
    bounds = _search_bounds(POINT, 50)
    assert bounds is not None
    plan = connection.execute(
        b"EXPLAIN (ANALYZE, FORMAT JSON) " + query, (POINT.latitude, POINT.longitude, 50, *bounds)
    ).fetchone()[0]
    assert "indexed_stations_location_idx" in json.dumps(plan), plan
    assert plan[0]["Plan"]["Actual Rows"] == 1
    assert StationCatalog(database).resolve(POINT).id == "1"


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


@pytest.mark.parametrize("directory", ["history"], indirect=True)
def test_lookup_and_station_refresh_use_indexes_with_weather_history(directory, record_property):
    """Neither selecting a source nor refreshing one ID should scan unrelated weather history."""
    from backend.station_catalog import _nearest_station_query, _search_bounds

    connection, database = directory
    for table in (*TABLES, "indexed_stations"):
        connection.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
    assert connection.execute("SELECT count(*) FROM daily_index").fetchone()[0] == 365001
    assert connection.execute("SELECT count(*) FROM indexed_stations").fetchone()[0] == 501
    bounds = _search_bounds(POINT, 50)
    assert bounds is not None
    queries = {
        "station_lookup": (_nearest_station_query(TABLES), (POINT.latitude, POINT.longitude, 50, *bounds)),
        "station_refresh": (b"SELECT * FROM station_metadata_summary WHERE station_id = %s", ("251",)),
    }
    for name, (query, values) in queries.items():
        plan = connection.execute(b"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, values).fetchone()[0][0]
        record_property(name, json.dumps(plan))
        nodes = list(_plan_nodes(plan["Plan"]))
        weather_scans = [node for node in nodes if node.get("Relation Name") in TABLES]
        assert {node["Relation Name"] for node in weather_scans} == set(TABLES), plan
        assert all(node["Node Type"] != "Seq Scan" for node in weather_scans), plan
        assert plan["Plan"]["Actual Rows"] == 1, plan
    assert StationCatalog(database).resolve(POINT).id == "1"
