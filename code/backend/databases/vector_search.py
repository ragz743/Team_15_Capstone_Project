"""Pgvector-backed semantic retrieval from PostgreSQL database."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

logger = logging.getLogger(__name__)

# CONSTANTS

# Row cap for any single retireval call (FR-13 query limits)
HARD_ROW_LIMIT = 20
# Maximum date-range span allowed for historical/aggregate queries (FR-13)
MAX_DATE_RANGE_DAYS = 90
# Table name (change here only)
_TABLE = "agwn_embeddings"

# DATA_TRANSFER OBJECTS


@dataclass
class ChunkMetadata:
    """There is metadata attached to every stored context chunk.

    This fields map to AWN domain concepts so metadata filters can narrow the ANN search before
    semantic scoring (see FR-11 and NFR-1).
    """

    station_id: str | None = None  # AWN station ID
    data_type: str | None = (
        None  # "live", "historical", "aggregate", or "schema"
    )
    data_start: str | None = (
        None  # Start date string (inclusive) for time-scoped chunks
    )
    data_end: str | None = (
        None  # End date string (inclusive) for time-scoped chunks
    )
    metric: str | None = (
        None  # Weather variable name (e.g., temperature, precipitation)
    )
    source_table: str | None = (
        None  # AWN MySQL table the chunk was derived from
    )
    extra: dict[str, Any] = field(
        default_factory=dict
    )  # Catch-all dict for muture metadata fields.

    def to_jsonb(self) -> str:
        """Serialize to a JSONB-compatible JSON string."""
        payload = {
            "station_id": self.station_id,
            "data_type": self.data_type,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "metric": self.metric,
            "source_table": self.source_table,
        }
        payload.update(self.extra)
        return json.dumps({k: v for k, v in payload.items() if v is not None})

    @classmethod
    def from_jsonb(cls, raw: str | dict) -> "ChunkMetadata":
        """Deserialize from a JSONB string on already-parsed dict."""
        data: dict = json.loads(raw) if isinstance(raw, str) else raw
        known = {
            "station_id",
            "data_type",
            "data_start",
            "data_end",
            "metric",
            "source_table",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            station_id=data.get("station_id"),
            data_type=data.get("data_type"),
            data_start=data.get("data_start"),
            data_end=data.get("data_end"),
            metric=data.get("metric"),
            source_table=data.get("source_table"),
            extra=extra,
        )


@dataclass
class RetrievedChunk:
    """A single chunk returned from a semantic search."""

    chunk_id: int
    content: str
    metadata: ChunkMetadata
    similarity: float  # cosine similarity in [0.00, 1.0]


# VECTORSTORE


class VectorStore:
    """Manages the pgvector embeddings table and exposes semantic search with JSONB metadata filtering.

    USAGE: Instantiate once at application startup, call connect(), then call search() for every user
    query. The write methods upsert_chunk and delete_by_station are for the offline loader pipeline and
    must NEVER be exposed via the chatbot API.
    """

    def __init__(
        self,
        embedding_dim: int = 1024,
        top_k: int = 6,
        similarity_threshold: float = 0.25,
        statement_timeout_ms: int = 8000,
    ) -> None:
        """Initialize the VectorStore configuration.

        Args:
            embedding_dim: Vector dimension (must match the embedding model).
            top_k: Max chunks returned per query. Kept small so the LLM context window stays within
                budget and responses stay fast (NFR-1).
            similarity_threshold: Minimum cosine similarity [0,1]. Chunk below this score are
                discarded to prevent low-quality context reaching the LLM (NFR-2).
            statement_timeout_ms: Per-query hard timeout applied at the Postgres session level (FR-13).
                Default is 8 seconds, which is within the 5 seconds average in NFR-1 budget when
                combined with typical LLM latency.

        """
        self.embedding_dim = embedding_dim
        self.top_k = min(top_k, HARD_ROW_LIMIT)
        self.similarity_threshold = similarity_threshold
        self.statement_timeout_ms = statement_timeout_ms
        self.__conn: psycopg2.extensions.connection | None = None

    # CONNECTION LIFESTYLE

    def connect(self) -> None:
        """Open a database connection using environment variables (FR-18).

        Must be called once before any other method. The application should call disconnect()
        at shutdown (FR-17).
        """
        self.__conn = psycopg2.connect(
            host=os.environ["PGVECTOR_HOST"],
            port=int(os.environ.get("PGVECTOR_PORT", 5432)),
            dbname=os.environ["PGVECTOR_DB"],
            user=os.environ["PGVECTOR_USER"],
            password=os.environ["PGVECTOR_PASSWORD"],
        )
        register_vector(self.__conn)
        # Apply per-session statement timeout (FR-13 and NFR-1)
        with self.__conn.cursor() as cur:
            cur.execute(
                f"SET statement_timeout TO {self.statement_timeout_ms};"
            )
        self.__conn.commit()  # type: ignore[union-attr]
        logger.info(
            "VectorStore: connected (host=%s db=%s)",
            os.environ.get("PGVECTOR_HOST"),
            os.environ.get("PGVECTOR_DB"),
        )

    def disconnect(self) -> None:
        """Gracefully close the connection (FR-17)."""
        if self.__conn and not self.__conn.closed:
            self.__conn.close()
            logger.info("VectorStore: disconnected")

    def __cursor(self) -> psycopg2.extras.RealDictCursor:
        """Return a dict cursor, raising if not connected."""
        if self.__conn is None or self.__conn.closed:
            raise RuntimeError(
                "VectorStore is not connected. Call connect() before querying."
            )
        return self.__conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # SCHEMA BOOTSTRAP

    def create_table(self) -> None:
        """Idempotently create the embeddings table, IVFFlat ANN index, and GIN metadata index.

        Run once during initial deployment or after a schema migration. Safe to call repeatedly.
        Uses IF NOT EXISTS guards throughout.

        Index notes:
        - IVFFlat with lists=100 suits up to ~1000000 rows; increase lists proportionally as the corpus grows
        - GIN on the JSONB column enables fast metadata pre-filtering before the ANN scan, keeping latency inside NFR-1
        """
        with self.__cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
          id BIGSERIAL PRIMARY KEY,
          content TEXT NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{{}}',
          embedding vector({self.embedding_dim}) NOT NULL
        );
        """
            )
            cur.execute(
                f"""
        CREATE INDEX IF NOT EXISTS {_TABLE}_embedding_ivfflat_idx
        ON {_TABLE}
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
        """
            )
            cur.execute(
                f"""
        CREATE INDEX IF NOT EXISTS {_TABLE}_metadata_gin_idx
        ON {_TABLE} USING GIN (metadata);
        """
            )
        self.__conn.commit()  # type: ignore[union-attr]
        logger.info("VectorStore: tables and indexes ready.")

    # WRITE PATH: Loader pipeline only, never exposed to users (FR-12)

    def upsert_chunk(
        self,
        # Human-readable text that will be injected into LLM prompts.
        content: str,
        # Float vector from the embedding model
        embedding: list[float],
        # Domain metadata for filtering
        metadata: ChunkMetadata,
    ) -> int:
        """Insert a single context chunk and return its assigned row ID.

        IMPORTANT: Call this method only from /code/backend/loaders/embed_and_load.py.
        It must NEVER be reachable from the chatbot request-handling code path (FR-12).
        """
        with self.__cursor() as cur:
            cur.execute(
                f"""
        INSERT INTO {_TABLE} (content, metadata, embedding)
        VALUES (%s, %s::jsonb, %s)
        RETURNING id;
        """,
                (content, metadata.to_jsonb(), embedding),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("INSERT returned no row - upsert failed.")
            row_id: int = row["id"]
        self.__conn.commit()  # type: ignore[union-attr]
        logger.debug("VectorStore: upserted id=%d", row_id)
        return row_id

    def delete_by_station(self, station_id: str) -> int:
        """Remove all chunks tagged with station_id (used for re-indexing).

        Returns the number of rows deleted. Loader pipeline only.
        """
        with self.__cursor() as cur:
            cur.execute(
                f"""DELETE FROM {_TABLE} WHERE metadata->>'station_id' = %s;""",
                (station_id,),
            )
            count: int = cur.rowcount
        self.__conn.commit()  # type: ignore[union-attr]
        logger.info(
            "VectorStore: deleted %d chunks for station=%s", count, station_id
        )
        return count

    # READ PATH: Semantic search (FR-4, FR-7-10, FR-12)

    def search(
        self,
        # Dense vector produced by the embedding model
        query_embedding: list[float],
        *,
        # Restrict to a specific AWN station (FR-11)
        station_id: str | None = None,
        # One of live/historical/forecast/aggregate/schema
        data_type: str | None = None,
        # Weather variable to scope retrieval (e.g., temperature)
        metric: str | None = None,
        # AWN MySQL table name to restrict context
        source_table: str | None = None,
        # Override instance-level top_k for this call
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Cosine-similarity semantic search with optional metadata pre-filtering.

        Metadata filters are pushed into the SQL WHERE clause so that the IVFFlat index only scans the
        relevant subset of the table, keeping latency inside NFR-1 (average of 5 seconds).
        All SQL is fully parameterized - no f-string interpolation of user-controlled values (NFR-5, OWASP).
        """
        k = min(top_k if top_k is not None else self.top_k, HARD_ROW_LIMIT)

        # Build parameterized WHERE predicates
        predicates: list[str] = []
        params: list[Any] = []

        if station_id is not None:
            predicates.append("metadata->>'station_id' = %s")
            params.append(station_id)
        if data_type is not None:
            predicates.append("metadata->>'data_type' = %s")
            params.append(data_type)
        if metric is not None:
            predicates.append("metadata->>'metric' = %s")
            params.append(metric)
        if source_table is not None:
            predicates.append("metadata->>'source_table' = %s")
            params.append(source_table)

        where = ("WHERE " + " AND ".join(predicates)) if predicates else ""

        # 1 - (cosine distance) = cosine similarity
        sql = f"""
        SELECT
            id,
            content,
            metadata,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {_TABLE}
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

        # query_embedding appears twice: once in SELECT list, once in ORDER BY
        all_params: list[Any] = (
            [query_embedding] + params + [query_embedding, k]
        )

        try:
            with self.__cursor() as cur:
                cur.execute(sql, all_params)
                rows = cur.fetchall()
        except psycopg2.errors.QueryCanceled:
            logger.warning(
                "VectorStore: search timed out (station=%s)", station_id
            )
            return []

        results: list[RetrievedChunk] = []
        for row in rows:
            sim = float(row["similarity"])
            if sim < self.similarity_threshold:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=row["id"],
                    content=row["content"],
                    metadata=ChunkMetadata.from_jsonb(dict(row["metadata"])),
                    similarity=sim,
                )
            )

        # Return list of RetrievedChunk sorted descending by cosine similarity, excluding any
        # chunks below similarity_threshold
        return results

    def search_multi_type(
        self,
        query_embedding: list[float],
        # List of data_type strings to query sequentially
        data_types: list[str],
        *,
        # Final cap after merging (defaults to instance top_k)
        top_k: int | None = None,
        **kwargs: Any,  # Forwarded to search() (station_id, metric, etc.)
    ) -> list[RetrievedChunk]:
        """Search across multiple data_type values and merge results.

        Used when a query spans more than one category (e.g. aggregate + schema context).
        Deduplicates by chunk_id and re-sorts by similarity before truncating to top_k.
        """
        k = min(top_k if top_k is not None else self.top_k, HARD_ROW_LIMIT)
        seen: set[int] = set()
        merged: list[RetrievedChunk] = []

        for dt in data_types:
            for chunk in self.search(query_embedding, data_type=dt, **kwargs):
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append(chunk)

        merged.sort(key=lambda c: c.similarity, reverse=True)
        return merged[:k]
