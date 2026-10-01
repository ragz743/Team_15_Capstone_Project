"""Look up the nearest indexed station without loading a station catalog."""

import math

from backend.databases.pgvector import PgVectorConnection
from backend.weather_query import QueryClarificationError, RequestedPoint, Station

INDEX_TABLES = ("daily_index", "live_index", "forecast_index")
EARTH_RADIUS_KM = 6371.0088


def _search_bounds(point: RequestedPoint, radius_km: float) -> tuple[float, float, float, float] | None:
    """Bound a spherical search circle and intersect it with supported coordinates."""
    angle = radius_km / EARTH_RADIUS_KM
    latitude_span = math.degrees(angle)
    south, north = max(45, point.latitude - latitude_span), min(50, point.latitude + latitude_span)
    if south > north:
        return None
    longitude_span = math.degrees(math.asin(min(1, math.sin(angle) / math.cos(math.radians(point.latitude)))))
    west, east = max(-125, point.longitude - longitude_span), min(-116, point.longitude + longitude_span)
    if west > east:
        return None
    padding = 1e-10
    return west - padding, south - padding, east + padding, north + padding


def _nearest_station_query(tables: tuple[str, ...]) -> bytes:
    """Restrict candidates geographically before measuring distance or reading weather indexes."""
    available = " UNION ALL ".join(f"SELECT 1 FROM {table} WHERE metadata->>'id' = s.station_id" for table in tables)
    return f"""
        WITH request AS (
            SELECT %s::double precision AS latitude, %s::double precision AS longitude,
                   %s::double precision AS radius_km
        )
        SELECT s.station_id, s.name, s.county, s.latitude, s.longitude, s.state
        FROM indexed_stations s CROSS JOIN request r
        CROSS JOIN LATERAL (
            SELECT {2 * EARTH_RADIUS_KM} * asin(sqrt(least(1.0, greatest(0.0,
                power(sin(radians(s.latitude - r.latitude) / 2), 2)
                + cos(radians(r.latitude)) * cos(radians(s.latitude))
                * power(sin(radians(s.longitude - r.longitude) / 2), 2)
            )))) AS km
        ) distance
        WHERE s.location <@ box(point(%s, %s), point(%s, %s))
          AND distance.km <= r.radius_km
          AND EXISTS ({available})
        ORDER BY distance.km, s.station_id
        LIMIT 1
    """.encode()


class StationCatalog:
    """Read one eligible station from the indexed station directory."""

    def __init__(
        self,
        database: PgVectorConnection,
        *,
        tables: tuple[str, ...] = INDEX_TABLES,
        radius_km: float = 50,
    ) -> None:
        """Reuse an existing connection and keep the supported search distance."""
        if not 0 < radius_km <= 100:
            raise ValueError("Invalid source radius")
        if not tables or any(table not in INDEX_TABLES for table in tables):
            raise ValueError("Unsupported weather indexes")
        self._database = database
        self._radius = radius_km
        self._query = _nearest_station_query(tables)

    def resolve(self, point: RequestedPoint) -> Station:
        """Return one nearby source or ask for a different map point."""
        bounds = _search_bounds(point, self._radius)
        if bounds is not None:
            values = (point.latitude, point.longitude, self._radius, *bounds)
            rows = list(self._database.simple_query(self._query, values))
            if rows:
                station_id, name, county, latitude, longitude, state = rows[0]
                return Station(station_id, name, county, str(latitude), str(longitude), state)
        raise QueryClarificationError(
            f"No indexed weather source is within {self._radius:g} km of that point. Choose another point on the map."
        )
