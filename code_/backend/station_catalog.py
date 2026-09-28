"""Reuse station metadata between questions."""

import time
from collections.abc import Callable, Iterable
from threading import Lock

from backend.weather_query import Station


class StationCatalog:
    """Keep station identities for a bounded time and serialize refreshes."""

    def __init__(
        self,
        load: Callable[[], Iterable[Station]],
        *,
        ttl: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Set the metadata loader and cache lifetime in seconds."""
        if ttl < 0:
            raise ValueError("Catalog lifetime cannot be negative")
        self._load, self._ttl, self._clock = load, ttl, clock
        self._lock = Lock()
        self._expires = 0.0
        self._stations: tuple[Station, ...] = ()

    def stations(self) -> list[Station]:
        """Return cached identities, retrying empty catalogs and failed refreshes."""
        with self._lock:
            if not self._stations or self._clock() >= self._expires:
                stations = tuple(dict.fromkeys(self._load()))
                self._stations = stations
                self._expires = self._clock() + self._ttl
            return list(self._stations)
