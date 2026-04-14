"""Loader for creating documents from the AWN daily database."""

from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple, Self, Sequence, override

from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.loaders._loader_base import _BaseLoader
from langchain_core.documents import Document


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


class DailyQueryResult(NamedTuple):
    """The data returned by the daily station query."""

    date: date
    avg_air_temp: Decimal
    avg_humidity: Decimal
    avg_wind_sp: Decimal

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a DailyQueryResult from a tuple."""
        match row:
            case (date, avg_air_temp, avg_humidity, avg_wind_sp):
                return cls(
                    date,
                    avg_air_temp,
                    avg_humidity,
                    avg_wind_sp,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)


class DailyLoader(_BaseLoader):
    """A loader for pulling and processing awn daily data."""

    def __init__(self) -> None:
        """Create an instance of the DailyLoader class."""

    def _query_stations(self) -> list[MetadataQueryResult]:
        """Get station names from the metadata table."""
        query_metadata = """
            SELECT UNIT_ID, STATION_NAME, COUNTY, STATE,
            STATION_LATDEG, STATION_LNGDEG
            FROM METADATA
            WHERE COUNTY = 'Whitman'
            """
        with AWNDatabaseConnection() as awn_conn:
            return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]

    def _query_station_daily(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[DailyQueryResult]:
        """Query stations from the daily db."""
        result: list[DailyQueryResult] = []  # type: ignore
        with AWNDailyDatabaseConnection() as awn_conn:
            for s in stations:
                query_daily = f"""
                    SELECT JULDATE, AVG_AIR_TEMP, AVG_HUMIDITY, AVG_WIND_SP
                    FROM station{s.unit_id}daily
                    WHERE JULDATE >= %s
                    """

                # prep table name and date
                yesterday = (date.today() - timedelta(weeks=4)).strftime("%Y-%m-%d")  # YYYY-MM-DD
                result.extend(
                    [DailyQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_daily, (yesterday,))]
                )
        return result

    @override
    def load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = self._query_stations()
        stations_daily = self._query_station_daily(metadata_results)
        for meta, station in zip(metadata_results, stations_daily, strict=False):
            d = Document(
                page_content=f"""
                On {station.date}, {meta.station} had
                an average air temp of {station.avg_air_temp},
                an average wind speed of {station.avg_wind_sp},
                and an average humidity of {station.avg_humidity}.
                """,
                metadata={
                    "date": station.date,
                    "county": meta.county,
                    "state": meta.state,
                    "latitude": meta.station_lat,
                    "longitude": meta.station_lng,
                },
            )
            docs.append(d)

        return docs
