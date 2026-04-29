"""Loader for creating documents from the AWN daily database."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple, Self, Sequence, override

from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.pgvector import PgVectorConnection
from backend.loaders import _common
from backend.loaders._common import MetadataQueryResult
from backend.loaders._loader_base import _BaseLoader
from backend.models._embedding_base import _BaseEmbedding
from langchain_core.documents import Document


class DailyQueryResult(NamedTuple):
    """The data returned by the daily station query."""

    date: str
    avg_air_temp: Decimal | None
    avg_humidity: Decimal | None
    sum_precip: Decimal | None
    avg_wind_sp: Decimal | None
    avg_wind_dir: Decimal | None

    @classmethod
    def from_tuple(cls, row: Sequence) -> Self:
        """Create a DailyQueryResult from a tuple."""
        match row:
            case (date, avg_air_temp, avg_humidity, sum_precip, avg_wind_sp, avg_wind_dir):
                return cls(
                    date.strftime("%Y-%m-%d"),
                    avg_air_temp,
                    avg_humidity,
                    sum_precip,
                    avg_wind_sp,
                    avg_wind_dir,
                )
            case _:
                msg = f"unrecognized tuple structure: {row}"
                raise ValueError(msg)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Self:
        """Create a DailyQueryResult from a tuple."""
        return cls(
            # lots of type ignores, types based on MySQL - annoying but ok for now!
            d["JULDATE"].strftime("%Y-%m-%d"),  # type: ignore
            d.get("AVG_AIR_TEMP"),  # type: ignore
            d.get("AVG_HUMIDITY"),  # type: ignore
            d.get("SUM_PRECIP"),  # type: ignore
            d.get("AVG_WIND_SP"),  # type: ignore
            d.get("AVG_WIND_DIR"),  # type: ignore
        )

    @staticmethod
    def get_units() -> list[str]:
        """Get the units for each field of the result type."""
        return ["", "F", "%", "inches of rain", "miles per hour", "degrees"]


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

    def _query_station_daily(
        self,
        stations: list[MetadataQueryResult],
    ) -> list[tuple[MetadataQueryResult, DailyQueryResult]]:
        """Query stations from the daily db."""
        result: list[tuple[MetadataQueryResult, DailyQueryResult]] = []
        with AWNDailyDatabaseConnection() as awn_conn:
            for s in stations:
                fields = [
                    (True, "JULDATE", datetime),
                    (s.air_temp, "AVG_AIR_TEMP", float),
                    (s.rel_humidity, "AVG_HUMIDITY", float),
                    (s.precip, "SUM_PRECIP", float),
                    (s.wind_speed, "AVG_WIND_SP", float),
                    (s.wind_dir, "AVG_WIND_DIR", float),
                ]
                filtered_fields = [(field, type_) for enabled, field, type_ in fields if enabled]
                config_tup = NamedTuple("cfg", filtered_fields)
                query_daily = f"""
                    SELECT {", ".join(config_tup._fields)}
                    FROM station{s.unit_id}daily
                    WHERE JULDATE >= %s
                    """

                # prep table name and date
                a_week_ago = (date.today() - timedelta(weeks=1)).strftime("%Y-%m-%d")  # YYYY-MM-DD
                intermediate = [config_tup(*tup) for tup in awn_conn.simple_query(query_daily, (a_week_ago,))]
                result.extend([(s, DailyQueryResult.from_dict(tup._asdict())) for tup in intermediate])

        return result

    @override
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        docs: list[Document] = []
        metadata_results = _common.query_stations()
        stations_daily = self._query_station_daily(metadata_results)
        for meta, station in stations_daily:
            d = Document(
                page_content=_common.to_markdown_table((station,), DailyQueryResult.get_units()),
                metadata={
                    "id": meta.unit_id,
                    "date": station.date,
                    "station": meta.station,
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
