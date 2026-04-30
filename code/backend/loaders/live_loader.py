"""Loader for creating documents from the AWN live database."""

import json
from datetime import datetime
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
    wind_dir: float

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a LiveQueryResult from a tuple."""
        match row:
            case (tstamp, air_temp, rel_humidity, precip, wind_speed, wind_dir):
                return cls(
                    tstamp.strftime("%Y-%m-%d %H:%M:%S"),
                    air_temp,
                    rel_humidity,
                    precip,
                    wind_speed,
                    wind_dir,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Self:
        """Create a DailyQueryResult from a tuple."""
        return cls(
            # lots of type ignores, types based on MySQL - annoying but ok for now!
            d["TSTAMP"].strftime("%Y-%m-%d"),  # type: ignore
            d.get("AIR_TEMP"),  # type: ignore
            d.get("REL_HUMIDITY"),  # type: ignore
            d.get("PRECIP"),  # type: ignore
            d.get("WIND_SP"),  # type: ignore
            d.get("WIND_DIR"),  # type: ignore
        )

    @staticmethod
    def get_units() -> list[str]:
        """Get the units for each field of the result type."""
        return ["", "F", "%", "inches of rain", "miles per hour", "degrees"]


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

    def _query_station_most_recent(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, LiveQueryResult]]:
        """Query the most recent weather status from each station."""
        result: list[tuple[MetadataQueryResult, LiveQueryResult]] = []
        with AWNDatabaseConnection() as awn_conn:
            for s in stations:
                fields = [
                    (True, "TSTAMP", datetime),
                    (s.air_temp, "AIR_TEMP", float),
                    (s.rel_humidity, "REL_HUMIDITY", float),
                    (s.precip, "PRECIP", float),
                    (s.wind_speed, "WIND_SPEED", float),
                    (s.wind_dir, "WIND_DIR", float),
                ]
                filtered_fields = [(field, type_) for enabled, field, type_ in fields if enabled]
                config_tup = NamedTuple("cfg", filtered_fields)
                # Always get the most recent (max) record for each station
                query_daily = f"""
                    SELECT {", ".join(config_tup._fields)}
                    FROM station{s.unit_id}
                    ORDER BY TSTAMP DESC
                    LIMIT 1;
                    """

                intermediate = [config_tup(*tup) for tup in awn_conn.simple_query(query_daily, ())]
                result.extend([(s, LiveQueryResult.from_dict(tup._asdict())) for tup in intermediate])
        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = _common.query_stations()
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
