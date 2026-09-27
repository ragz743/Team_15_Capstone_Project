"""Loader for creating documents from AWN forecast databases."""

import json
from datetime import datetime
from typing import NamedTuple, Self, Sequence, override

import mysql.connector
from backend.databases.awn_fc_connection import (
    AWNForecastDatabaseConnection,
    AWNForecastFallbackDatabaseConnection,
)
from backend.databases.pgvector import PgVectorConnection
from backend.loaders import _common
from backend.loaders._common import MetadataQueryResult
from backend.loaders._loader_base import _BaseLoader
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document


class PrimaryForecastQueryResult(NamedTuple):
    """Result from the primary forecast table (fcst_{unit_id}_{year})."""

    forecast_time: str
    air_temp: float
    solar_rad: int
    soil_temp_8in: float

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a PrimaryForecastQueryResult from a row tuple."""
        match row:
            case (forecast_time, air_temp, solar_rad, soil_temp_8in):
                return cls(
                    forecast_time.strftime("%Y-%m-%d %H:%M:%S"),
                    air_temp,
                    solar_rad,
                    soil_temp_8in,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @staticmethod
    def get_units() -> list[str]:
        """Return units for each field."""
        return ["", "F", "W/m²", "F"]


class FallbackForecastQueryResult(NamedTuple):
    """Result from the fallback forecast table (forecast{unit_id}) — full weather suite."""

    forecast_time: str
    air_temp: float
    rel_humidity: float
    wind_speed: float
    wind_dir: float
    precip: float

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a FallbackForecastQueryResult from a row tuple."""
        match row:
            case (tstamp, air_temp, rel_humidity, wind_speed, wind_dir, precip):
                return cls(
                    tstamp.strftime("%Y-%m-%d %H:%M:%S"),
                    air_temp,
                    rel_humidity,
                    wind_speed,
                    wind_dir,
                    precip,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @staticmethod
    def get_units() -> list[str]:
        """Return units for each field."""
        return ["", "F", "%", "mph", "degrees", "inches"]


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
        """Create an instance of the ForecastLoader class."""
        self._embedding_model = embedding_model

    def _query_station_current_forecast(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, list, list[str]]]:
        """Query the current forecast for each station.

        Returns tuples of (station_metadata, forecast_rows, units) so the
        caller does not need to know which table schema was used.
        """
        result: list[tuple[MetadataQueryResult, list, list[str]]] = []
        with AWNForecastDatabaseConnection() as awn_conn, AWNForecastFallbackDatabaseConnection() as fallback_conn:
            for s in stations:
                try:
                    table = f"fcst_{s.unit_id}_{self._year}"
                    query_forecast = f"""
                        SELECT Forecast_time, AIR_TEMP, SOLAR_RAD, SOIL_TEMP_8_IN
                        FROM {table}
                        WHERE Init_time = (SELECT MAX(Init_time) FROM {table})
                        LIMIT 24;
                        """
                    rows = [
                        PrimaryForecastQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_forecast, ())
                    ]
                    result.append((s, rows, PrimaryForecastQueryResult.get_units()))

                except mysql.connector.Error:
                    try:
                        table = f"forecast{s.unit_id}"
                        query_forecast = f"""
                            SELECT TSTAMP, AIR_TEMP, REL_HUMIDITY, WIND_SPEED, WIND_DIR, PRECIP
                            FROM {table}
                            WHERE
                                INDATE = (SELECT MAX(INDATE) FROM {table}) AND
                                INTIME = (SELECT MAX(INTIME) FROM {table})
                            LIMIT 24;
                            """
                        rows = [
                            FallbackForecastQueryResult.from_tuple(tup)
                            for tup in fallback_conn.simple_query(query_forecast, ())
                        ]
                        result.append((s, rows, FallbackForecastQueryResult.get_units()))

                    except mysql.connector.Error:
                        pass  # no forecast table for this station

        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = _common.query_stations()
        stations_forecast = self._query_station_current_forecast(metadata_results)
        for meta, forecast_rows, units in [(m, r, u) for m, r, u in stations_forecast if r]:
            init_time = forecast_rows[0].forecast_time
            header = f"Station: {meta.station} (ID: {meta.unit_id}) — {meta.county} County, {meta.state}\n\n"
            d = Document(
                page_content=header + _common.to_markdown_table(forecast_rows, units),
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
