"""Loader for creating documents from AWN forecast databases."""

import json
from datetime import datetime
from typing import NamedTuple, Self, Sequence, override

import mysql.connector
from backend.databases.awn_fc_connection import (
    AWNForecastDatabaseConnection,
    AWNForecastFallbackDatabaseConnection,
)
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.databases.pgvector import PgVectorConnection
from backend.loaders import _common
from backend.loaders._common import MetadataQueryResult
from backend.loaders._loader_base import _BaseLoader
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document


class ForecastQueryResult(NamedTuple):
    """The results for the loader forecast query."""

    forecast_time: str
    air_temp: float

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a LiveQueryResult from a tuple."""
        match row:
            case (tstamp, air_temp):
                return cls(
                    tstamp.strftime("%Y-%m-%d %H:%M:%S"),
                    air_temp,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @staticmethod
    def get_units() -> list[str]:
        """Get the units for each field of the result type."""
        return ["", "F"]


class ForecastLoader(_BaseLoader):
    """Loader for processing forecast data."""

    _year = datetime.now().strftime("%Y")  # current year class var, compute once

    insert_sql = b"""
    INSERT INTO forecast_index (id, embedding, document, metadata)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (id)
    DO UPDATE SET
        embedding = EXCLUDED.embedding,
        document = EXCLUDED.document,
        metadata = EXCLUDED.metadata
    RETURNING id;
    """

    def __init__(self, embedding_model: _BaseEmbedding) -> None:
        """Create and instance of the ForecastLoader class."""
        self._embedding_model = embedding_model

    def _query_stations(self) -> list[MetadataQueryResult]:
        # TODO (Gavin): extract meta data query into a common class for all loaders
        """Get station names from the metadata table."""
        query_metadata = """
            SELECT UNIT_ID, STATION_NAME, COUNTY, STATE,
            STATION_LATDEG, STATION_LNGDEG
            FROM METADATA
            WHERE COUNTY = 'Whitman' AND ACTIVE_STATION = "Y"
           """
        with AWNDatabaseConnection() as awn_conn:
            return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]

    def _query_station_current_forecast(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, list[ForecastQueryResult]]]:
        """Query the current forecast for a station."""
        result: list[tuple[MetadataQueryResult, list[ForecastQueryResult]]] = []
        with AWNForecastDatabaseConnection() as awn_conn, AWNForecastFallbackDatabaseConnection() as fallback_conn:
            # query grabs most recent set of forecasts for a station
            limit = "LIMIT 4"
            for s in stations:
                try:
                    table = f"fcst_{s.unit_id}_{self._year}"
                    query_forecast = f"""
                        SELECT Forecast_time, AIR_TEMP
                        FROM {table}
                        WHERE Init_time = (SELECT MAX(Init_time) FROM {table})
                        {limit};
                        """
                    forecast_table = [
                        ForecastQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_forecast, ())
                    ]

                    result.append((s, forecast_table))

                except mysql.connector.Error:  # query from fallback if table does not exist
                    table = f"forecast{s.unit_id}"
                    query_forecast = f"""
                        SELECT INDATE, INTIME, AIR_TEMP
                        FROM {table}
                        WHERE
                            INDATE = (SELECT MAX(INDATE) FROM {table}) AND
                            INTIME = (SELECT MAX(INTIME) FROM {table})
                        {limit};
                        """
                    forecast_table = [
                        ForecastQueryResult.from_tuple((datetime.combine(date, time), air_temp))
                        for date, time, air_temp in fallback_conn.simple_query(query_forecast, ())
                    ]

                    result.append((s, forecast_table))

        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = self._query_stations()
        stations_forecast = self._query_station_current_forecast(metadata_results)
        for meta, forecast_table in [(m, s) for m, s in stations_forecast if s]:
            init_time = forecast_table[0].forecast_time  # each forecast made at the same time, just use one
            d = Document(
                # each forecast gets a summary, leave a blank line between for LLM readability
                page_content=_common.to_markdown_table(forecast_table, ForecastQueryResult.get_units()),
                metadata={
                    "id": meta.unit_id,
                    "station": meta.station,
                    "timestamp": init_time,
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
                pgvec_conn.insert(
                    self.insert_sql, (doc.metadata["id"], vec, doc.page_content, json.dumps(doc.metadata))
                )
                for vec, doc in embeddings
            ]

        return ids
