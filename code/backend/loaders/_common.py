"""The common Metadata table type to be called from other loaders during table selection."""

import itertools
from typing import NamedTuple, Self, Sequence

from backend.databases.awn_main_connection import AWNDatabaseConnection


class MetadataQueryResult(NamedTuple):
    """The data returned by the metadata query."""

    unit_id: str
    station: str
    county: str
    state: str
    station_lat: str
    station_lng: str
    air_temp: bool
    rel_humidity: bool
    precip: bool
    wind_speed: bool
    wind_dir: bool

    @classmethod
    def from_tuple(cls, row: Sequence[object]) -> Self:
        """Create a MetadataQueryResult from a tuple."""
        match row:
            case (
                str(unit),
                str(station),
                str(county),
                str(state),
                str(lat),
                str(lng),
                str(air_temp),
                str(rel_humid),
                str(precip),
                str(wind_spd),
                str(wind_dir),
            ):
                return cls(
                    unit,
                    station,
                    county,
                    state,
                    lat,
                    lng,
                    air_temp == "Y",
                    rel_humid == "Y",
                    precip == "Y",
                    wind_spd == "Y",
                    wind_dir == "Y",
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)


def query_stations() -> list[MetadataQueryResult]:
    """Get station names from the metadata table."""
    query_metadata = """
        SELECT UNIT_ID, STATION_NAME, COUNTY, STATE,
        STATION_LATDEG, STATION_LNGDEG, AIR_TEMP,
        REL_HUMIDITY, PRECIP, WIND_SPEED, WIND_DIR
        FROM METADATA
        WHERE
        COUNTY = 'Whitman' OR
        COUNTY = 'Spokane' OR
        COUNTY = 'Douglas' AND
        ACTIVE_STATION = "Y";
        """
    with AWNDatabaseConnection() as awn_conn:
        return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]


def to_markdown_table(tuples: Sequence[NamedTuple], units: list[str]) -> str:
    """Convert a collection of named tuple object into a markdown table."""
    columns = zip(tuples[0]._fields, units, strict=True)
    header = "| " + " | ".join(f"{col}{' in ' + unit if unit else ''}" for col, unit in columns) + " |\n"
    divider = "| " + " | ".join(itertools.repeat("---", len(units))) + " |\n"
    rows = ["| " + " | ".join(map(str, row)) + " |\n" for row in tuples]

    return header + divider + "".join(rows)
