"""Validated locations and date bounds for weather retrieval."""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class QueryClarificationError(ValueError):
    """A request needs more information before records can be selected."""


class RequestedPoint(BaseModel):
    """A point chosen by the user, never a source station coordinate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@dataclass(frozen=True)
class Station:
    """An indexed identity with private coordinates for source selection."""

    id: str
    name: str
    county: str
    latitude: str | None = None
    longitude: str | None = None
    state: str = ""


@dataclass(frozen=True)
class WeatherQuery:
    """Inclusive dates and server selected station IDs applied before ranking."""

    station_ids: tuple[str, ...]
    start: date
    end: date
    county: str | None = None

    def __post_init__(self) -> None:
        """Reject an empty scope or invalid period before database access."""
        if not self.station_ids or any(not value.isdecimal() for value in self.station_ids):
            raise ValueError("A weather query requires valid station IDs")
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("A weather query requires ordered calendar dates")


def washington_today() -> date:
    """Use the same calendar for interpretation and index freshness checks."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()
