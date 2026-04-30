"""Loader for creating documents from the AWN daily database."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple, Self, Sequence, override

from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.databases.pgvector import PgVectorConnection
from backend.loaders._common import MetadataQueryResult
from backend.loaders._loader_base import _BaseLoader
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document


class DailyQueryResult(NamedTuple):
    """The data returned by the daily station query."""

    date: str
    avg_air_temp: Decimal
    avg_humidity: Decimal
    avg_wind_sp: Decimal

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a DailyQueryResult from a tuple."""
        match row:
            case (date, avg_air_temp, avg_humidity, avg_wind_sp):
                return cls(
                    date.strftime("%Y-%m-%d"),
                    avg_air_temp,
                    avg_humidity,
                    avg_wind_sp,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)


class DailyLoader(_BaseLoader):
    """A loader for pulling and processing awn daily data."""

    insert_sql = b"""
    INSERT INTO daily_index (embedding, document, metadata)
    VALUES (%s, %s, %s)
    RETURNING id;
    """

    def __init__(self, embedding_model: _BaseEmbedding) -> None:
        """Create an instance of the DailyLoader class."""
        self._embedding_model = embedding_model

    def _query_stations(self) -> list[MetadataQueryResult]:
        """Get station names from the metadata table."""
        query_metadata = """
            SELECT UNIT_ID, STATION_NAME, COUNTY, STATE,
            STATION_LATDEG, STATION_LNGDEG
            FROM METADATA
            WHERE COUNTY = 'Whitman' AND ACTIVE_STATION = "Y"
           """
        with AWNDatabaseConnection() as awn_conn:
            return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]

    def _query_station_daily(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, DailyQueryResult]]:
        """Query stations from the daily db."""
        result: list[tuple[MetadataQueryResult, DailyQueryResult]] = []
        with AWNDailyDatabaseConnection() as awn_conn:
            for s in stations:
                query_daily = f"""
                    SELECT JULDATE, AVG_AIR_TEMP, AVG_HUMIDITY, AVG_WIND_SP
                    FROM station{s.unit_id}daily
                    WHERE JULDATE >= %s
                    """

                # prep table name and date
                a_month_ago = (date.today() - timedelta(weeks=4)).strftime("%Y-%m-%d")  # YYYY-MM-DD
                result.extend(
                    [
                        (s, DailyQueryResult.from_tuple(tup))
                        for tup in awn_conn.simple_query(query_daily, (a_month_ago,))
                    ]
                )
        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = self._query_stations()
        stations_daily = self._query_station_daily(metadata_results)
        for meta, station in stations_daily:
            d = Document(
                page_content=f"""
                On {station.date}, {meta.station} had
                an average air temp of {station.avg_air_temp},
                an average wind speed of {station.avg_wind_sp},
                and an average humidity of {station.avg_humidity}.
                """.strip(),
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

    @override
    def _store(self, docs: list[Document]) -> list[str]:
        """Given a list of documents, store them in the vector store."""
        embeddings = self._embedding_model.embed_documents(docs)

        with PgVectorConnection() as pgvec_conn:
            ids = [
                pgvec_conn.insert(self.insert_sql, (vec, doc.page_content, json.dumps(doc.metadata)))
                for vec, doc in embeddings
            ]

        return ids
