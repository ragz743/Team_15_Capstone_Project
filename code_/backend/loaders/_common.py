"""The common Metadata table type to be called from other loaders during table selection."""

import itertools
from decimal import Decimal
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
        (COUNTY = 'Whitman' OR
        COUNTY = 'Spokane' OR
        COUNTY = 'Douglas') AND
        ACTIVE_STATION = "Y";
        """
    with AWNDatabaseConnection() as awn_conn:
        return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]


def _format_cell(value: object) -> str:
    """Render one measurement, trimming float noise to a single decimal place.

    MySQL hands back Decimal for measurement columns despite the float
    annotations on the query result tuples, so both types are handled here.
    """
    if isinstance(value, (float, Decimal)):
        return f"{value:.1f}"
    return str(value)


def _filter_none_columns(tuples: Sequence[NamedTuple], units: list[str]) -> list[tuple[int, str, str]]:
    """Return column metadata for columns that contain at least one value."""
    return [
        (index, name, unit)
        for index, (name, unit) in enumerate(zip(tuples[0]._fields, units, strict=True))
        if any(row[index] is not None for row in tuples)
    ]


def _format_markdown_table(tuples: Sequence[NamedTuple], columns: list[tuple[int, str, str]]) -> str:
    """Render selected columns and rows as a markdown table."""
    header = "| " + " | ".join(f"{name}{' in ' + unit if unit else ''}" for _, name, unit in columns) + " |\n"
    divider = "| " + " | ".join(itertools.repeat("---", len(columns))) + " |\n"
    rows = ["| " + " | ".join(_format_cell(row[index]) for index, _, _ in columns) + " |\n" for row in tuples]

    return header + divider + "".join(rows)


def to_markdown_table(tuples: Sequence[NamedTuple], units: list[str]) -> str:
    """Convert a collection of named tuple object into a markdown table."""
    if len(tuples[0]) != len(units):
        msg = f"data and unit mismatch:\ndata='{tuples}'\nunits='{units}'"
        raise ValueError(msg)
    columns = _filter_none_columns(tuples, units)
    return _format_markdown_table(tuples, columns)
