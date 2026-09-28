"""Cached geographic source lookup without exposing station coordinates."""

import math
import time
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Lock

from backend.weather_query import QueryClarificationError, RequestedPoint, Station


@dataclass(frozen=True)
class LocatedStation:
    """A consistent indexed identity and its normalized private coordinates."""

    station: Station
    latitude: float
    longitude: float


def _coordinates(station: Station) -> tuple[float, float] | None:
    try:
        lat, lon = float(station.latitude or ""), float(station.longitude or "")
    except (ValueError, TypeError):
        return None
    if station.state.strip().casefold() not in {"wa", "washington"}:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and 45 <= lat <= 50 and 116 <= abs(lon) <= 125):
        return None
    return lat, -abs(lon)


def _located_stations(records: Iterable[Station]) -> tuple[LocatedStation, ...]:
    grouped: dict[str, list[Station]] = {}
    for station in records:
        if station.id.isdecimal() and station.name.strip():
            grouped.setdefault(station.id, []).append(station)
    located = []
    for versions in grouped.values():
        identities = {(s.name.strip().casefold(), s.county.strip().casefold()) for s in versions}
        coordinates = {point for s in versions if (point := _coordinates(s)) is not None}
        if len(identities) == 1 and len(coordinates) == 1:
            located.append(LocatedStation(versions[0], *coordinates.pop()))
    return tuple(sorted(located, key=lambda value: value.latitude))


def _distance(point: RequestedPoint, station: LocatedStation) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (point.latitude, point.longitude, station.latitude, station.longitude))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, value))))


class StationCatalog:
    """Refresh identities once per TTL and search a latitude band in memory."""

    def __init__(
        self,
        load: Callable[[], Iterable[Station]],
        *,
        ttl: float = 300,
        radius_km: float = 50,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Set the cache lifetime and the maximum supported source distance."""
        if ttl < 0 or not 0 < radius_km <= 100:
            raise ValueError("Invalid catalog lifetime or source radius")
        self._load, self._ttl, self._radius, self._clock = load, ttl, radius_km, clock
        self._lock = Lock()
        self._expires = 0.0
        self._stations: tuple[LocatedStation, ...] = ()
        self._latitudes: tuple[float, ...] = ()

    def _snapshot(self) -> tuple[tuple[LocatedStation, ...], tuple[float, ...]]:
        with self._lock:
            if not self._stations or self._clock() >= self._expires:
                stations = _located_stations(self._load())
                self._stations = stations
                self._latitudes = tuple(station.latitude for station in stations)
                self._expires = self._clock() + self._ttl
            return self._stations, self._latitudes

    def resolve(self, point: RequestedPoint) -> Station:
        """Choose the nearest indexed source within the supported distance."""
        stations, latitudes = self._snapshot()
        band = math.degrees(self._radius / 6371.0088)
        candidates = stations[
            bisect_left(latitudes, point.latitude - band) : bisect_right(latitudes, point.latitude + band)
        ]
        nearest = min(
            ((_distance(point, station), station.station.id, station.station) for station in candidates),
            default=None,
            key=lambda value: (value[0], value[1]),
        )
        if nearest is None or nearest[0] > self._radius:
            raise QueryClarificationError(
                f"No indexed weather source is within {self._radius:g} km of that point. "
                "Choose another point on the map."
            )
        return nearest[2]
