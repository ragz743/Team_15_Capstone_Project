"""The common Metadata table type to be called from other loaders during table selection."""

import itertools
from typing import NamedTuple, Self, Sequence


class MetadataQueryResult(NamedTuple):
    """The data returned by the metadata query."""

    unit_id: str
    station: str
    county: str
    state: str
    station_lat: str
    station_lng: str

    @classmethod
    def from_tuple(cls, row: Sequence[object]) -> Self:
        """Create a MetadataQueryResult from a tuple."""
        match row:
            case (str(unit), str(station), str(county), str(state), str(lat), str(lng)):
                return cls(
                    unit,
                    station,
                    county,
                    state,
                    lat,
                    lng,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)


def to_markdown_table(tuples: Sequence[NamedTuple], units: list[str]) -> str:
    """Convert a collection of named tuple object into a markdown table."""
    columns = zip(tuples[0]._fields, units, strict=True)
    header = "| " + " | ".join(f"{col}{' in ' + unit if unit else ''}" for col, unit in columns) + " |\n"
    divider = "| " + " | ".join(itertools.repeat("---", len(units))) + " |\n"
    rows = ["| " + " | ".join(map(str, row)) + " |\n" for row in tuples]

    return header + divider + "".join(rows)
