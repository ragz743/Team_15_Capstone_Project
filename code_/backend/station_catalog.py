"""Cached geographic source lookup without exposing station coordinates."""

import math
import time
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Lock

from backend.weather_query import QueryClarificationError, RequestedPoint, Station
from pydantic import BaseModel, ConfigDict, Field


class PublicStation(BaseModel):
    """Station identity and optional distance for the picker."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    county: str
    distance_km: float | None = None


class StationList(BaseModel):
    """Browsable stations without their coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    stations: list[PublicStation] = Field(default_factory=list)
    counties: list[str] = Field(default_factory=list)
    located_count: int = 0


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


def _consistent_stations(records: Iterable[Station]) -> list[tuple[Station, tuple[float, float] | None]]:
    grouped: dict[str, list[Station]] = {}
    for station in records:
        if station.id.isascii() and station.id.isdecimal() and len(station.id) <= 20 and station.name.strip():
            grouped.setdefault(station.id, []).append(station)
    stations = []
    for versions in grouped.values():
        identities = {(s.name.strip().casefold(), s.county.strip().casefold()) for s in versions}
        if len(identities) != 1:
            continue
        coordinates = {point for s in versions if (point := _coordinates(s)) is not None}
        stations.append((versions[0], coordinates.pop() if len(coordinates) == 1 else None))
    return stations


def _located_stations(records: Iterable[Station]) -> tuple[LocatedStation, ...]:
    located = [LocatedStation(station, *point) for station, point in _consistent_stations(records) if point]
    return tuple(sorted(located, key=lambda value: value.latitude))


def _distance(point: RequestedPoint, station: LocatedStation) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (point.latitude, point.longitude, station.latitude, station.longitude))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def browse_stations(records: Iterable[Station], point: RequestedPoint | None = None) -> StationList:
    """Sort public identities by name or distance without selecting a station."""
    ranked = []
    located = 0
    for station, coordinate in _consistent_stations(records):
        located += coordinate is not None
        distance = _distance(point, LocatedStation(station, *coordinate)) if point and coordinate else None
        public = PublicStation(
            id=station.id,
            name=station.name.strip(),
            county=station.county.strip(),
            distance_km=round(distance, 1) if distance is not None else None,
        )
        ranked.append((distance if distance is not None else math.inf, public))
    ranked.sort(key=lambda item: (item[0], item[1].name.casefold(), item[1].id))
    stations = [station for _, station in ranked]
    return StationList(
        stations=stations,
        counties=sorted({station.county for station in stations if station.county}),
        located_count=located,
    )


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
