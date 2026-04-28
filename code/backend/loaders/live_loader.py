"""Loader for creating documents from the AWN live database."""

import json
from typing import NamedTuple, Self, Sequence, override

from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.databases.pgvector import PgVectorConnection
from backend.loaders import _common
from backend.loaders._common import MetadataQueryResult
from backend.loaders._loader_base import _BaseLoader
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document


class LiveQueryResult(NamedTuple):
    """The result of the live data loader query."""

    timestamp: str
    air_temp: float
    rel_humidity: float
    precipitation: float
    wind_speed: float

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a LiveQueryResult from a tuple."""
        match row:
            case (tstamp, air_temp, rel_humidity, precip, wind_speed):
                return cls(
                    tstamp.strftime("%Y-%m-%d %H:%M:%S"),
                    air_temp,
                    rel_humidity,
                    precip,
                    wind_speed,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @staticmethod
    def get_units() -> list[str]:
        """Get the units for each field of the result type."""
        return ["", "F", "%", "inches of rain", "miles per hour"]


class LiveLoader(_BaseLoader):
    """A loader for processing live station data."""

    insert_sql = b"""
    INSERT INTO live_index (id, embedding, document, metadata)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (id)
    DO UPDATE SET
        embedding = EXCLUDED.embedding,
        document = EXCLUDED.document,
        metadata = EXCLUDED.metadata
    RETURNING id;
    """

    def __init__(self, embedding_model: _BaseEmbedding) -> None:
        """Create an instance of the LiveLoader class."""
        self._embedding_model = embedding_model

    def _query_stations(self) -> list[MetadataQueryResult]:
        # TODO (Gavin): extract meta data query into a common class for all loaders
        """Get station names from the metadata table."""
        query_metadata = """
            SELECT UNIT_ID, STATION_NAME, COUNTY, STATE,
            STATION_LATDEG, STATION_LNGDEG
            FROM METADATA
            WHERE
            COUNTY = 'Whitman' AND
            ACTIVE_STATION = "Y";
           """
        with AWNDatabaseConnection() as awn_conn:
            return [MetadataQueryResult.from_tuple(tup) for tup in awn_conn.simple_query(query_metadata, ())]

    def _query_station_most_recent(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, LiveQueryResult]]:
        """Query the most recent weather status from each station."""
        result: list[tuple[MetadataQueryResult, LiveQueryResult]] = []
        with AWNDatabaseConnection() as awn_conn:
            for s in stations:
                # Always get the most recent (max) record for each station
                query_daily = f"""
                    SELECT TSTAMP, AIR_TEMP, REL_HUMIDITY, PRECIP, WIND_SPEED
                    FROM station{s.unit_id}
                    ORDER BY TSTAMP DESC
                    LIMIT 1;
                    """

                result.extend([(s, LiveQueryResult.from_tuple(tup)) for tup in awn_conn.simple_query(query_daily, ())])
        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = self._query_stations()
        stations_live = self._query_station_most_recent(metadata_results)
        for meta, station in stations_live:
            d = Document(
                page_content=_common.to_markdown_table((station,), LiveQueryResult.get_units()),
                metadata={
                    "id": meta.unit_id,
                    "station": meta.station,
                    "timestamp": station.timestamp,
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
