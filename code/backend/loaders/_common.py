"""The common Metadata table type to be called from other loaders during table selection."""

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
