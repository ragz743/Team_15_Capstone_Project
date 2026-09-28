"""The vector store wrapper class."""

import json
from datetime import date

from backend.databases.pgvector import PgVectorConnection
from backend.models._embedding_base import _BaseEmbedding
from backend.weather_query import Station, WeatherQuery
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from psycopg import sql

_TIMESTAMP_KEYS: dict[str, str] = {
    "daily_index": "date",
    "live_index": "timestamp",
    "forecast_index": "timestamp",
}

# Allowlist for keys interpolated into SQL by distinct_metadata_values.
_FILTERABLE_KEYS = frozenset({"station", "county", "state", "id"})


class PgVectorStore(VectorStore):
    """The local pgvector postgreSQL VectorStore class."""

    _embedding_model: _BaseEmbedding
    _vector_db: PgVectorConnection
    _table: str
    _staleness_days: int | None

    _ALLOWED_TABLES = frozenset({"daily_index", "live_index", "forecast_index"})

    def __init__(
        self,
        embedding_model: _BaseEmbedding,
        table: str = "daily_index",
        staleness_days: int | None = None,
    ) -> None:
        """Create an instance of the PgVectorStore class.

        Args:
            embedding_model: Model used to embed query strings.
            table: Which index table to search.
            staleness_days: When set, similarity_search excludes documents whose
                metadata timestamp is older than this many days. Useful for
                filtering out defunct stations from live_index.

        """
        if table not in self._ALLOWED_TABLES:
            msg = f"unsupported vector store table: {table}"
            raise ValueError(msg)

        self._embedding_model = embedding_model
        self._vector_db = PgVectorConnection()
        self._table = table
        self._staleness_days = staleness_days

    @property
    def table(self) -> str:
        """Return the name of the index table this store queries."""
        return self._table

    def distinct_metadata_values(self, key: str) -> list[str]:
        """Return every distinct value stored under a metadata key in this table."""
        if key not in _FILTERABLE_KEYS:
            msg = f"unsupported metadata key: {key}"
            raise ValueError(msg)

        query = f"SELECT DISTINCT metadata->>'{key}' FROM {self._table}".encode()
        rows = self._vector_db.simple_query(query, ())
        return [row[0] for row in rows if row[0]]

    # Batches embedding via embed_documents, then inserts each (embedding, document, metadata) row
    # Metadata is json.dumps(..., default=str) to safely serialize date values from DailyLoader.
    # Returns auto-generated row IDs.
    def add_documents(self, documents: list[Document], **kwargs) -> list[str]:
        # TODO: (Gavin) Function is fine for now, but not needed as loaders are decoupled from pgvector. The current
        # setup should never load embeddings into the vector store using the vector store object.
        # In other words, the vector store class is only for retrieval.
        """Add or update documents in the vector store."""
        embeddings = self._embedding_model.embed_documents(documents)
        ids: list[str] = []
        with self._vector_db.conn.cursor() as cursor:
            for doc, (vec, _) in zip(documents, embeddings, strict=True):
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                query = sql.SQL(
                    "INSERT INTO {} (embedding, document, metadata) VALUES (%s, %s, %s) RETURNING id"
                ).format(sql.Identifier(self._table))
                cursor.execute(
                    query,
                    (vec_str, doc.page_content, json.dumps(doc.metadata, default=str)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Insert failed: no row returned")
                ids.append(str(row[0]))
        self._vector_db.conn.commit()
        return ids

    def aadd_documents(self, documents, **kwargs):
        """Async add or update documents in the vector store."""
        raise NotImplementedError

    def stations(self) -> list[Station]:
        """Read current station identities without caching failed or empty catalogs."""
        rows = self._vector_db.simple_query(
            (
                f"SELECT DISTINCT metadata->>'id', metadata->>'station', metadata->>'county' FROM {self._table} "
                "WHERE metadata->>'id' IS NOT NULL AND metadata->>'station' IS NOT NULL ORDER BY 2, 1"
            ).encode(),
            (),
        )
        return [Station(str(row[0]), str(row[1]), str(row[2] or "")) for row in rows]

    # Embeds the query string, then runs pgvector's <-> L2 nearest-neighbour operation and returns top-k results
    # as Document objects. Optional filter (JSONB containment) and staleness_days (date cutoff) are combined
    # into a WHERE clause before ranking — both may be active simultaneously.
    def similarity_search(
        self, query: str, k: int = 4, filter: dict | None = None, *, selection: WeatherQuery | None = None, **kwargs
    ) -> list[Document]:
        """Return a list of documents found during semantic search.

        Args:
            query: Natural-language query string to embed and search.
            k: Maximum number of results to return.
            filter: Optional dict of metadata key-value pairs; only rows whose
                metadata contains all pairs (JSONB @> containment) are returned.
            selection: Station IDs and inclusive date bounds applied before ranking.
            **kwargs: Ignored; present for LangChain VectorStore interface compatibility.

        """
        query_vec, _ = self._embedding_model.embed_document(Document(page_content=query))
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        where_clauses: list[str] = []
        query_vars: list = []

        if selection is not None:
            if self._table == "forecast_index":
                # Older indexes stored only the first forecast timestamp; recover dates from their table rows.
                dates = (
                    "jsonb_array_elements_text(CASE WHEN jsonb_typeof(metadata->'dates') = 'array' "
                    "THEN metadata->'dates' ELSE COALESCE((SELECT jsonb_agg(m[1]) FROM "
                    r"regexp_matches(document, '\|[ ]*([0-9]{4}-[0-9]{2}-[0-9]{2})[ T]', 'g') m), "
                    "'[]'::jsonb) END) AS forecast_date"
                )
                date_filter = f"EXISTS (SELECT 1 FROM {dates} WHERE forecast_date >= %s AND forecast_date <= %s)"
            else:
                field = "date" if self._table == "daily_index" else "timestamp"
                date_filter = f"left(metadata->>'{field}', 10) >= %s AND left(metadata->>'{field}', 10) <= %s"
            where_clauses.extend(["metadata->>'id' = ANY(%s)", date_filter])
            query_vars.extend([list(selection.station_ids), selection.start.isoformat(), selection.end.isoformat()])
            if selection.county:
                where_clauses.append("lower(metadata->>'county') = %s")
                query_vars.append(selection.county.casefold())

        if filter:
            where_clauses.append("metadata @> %s::jsonb")
            query_vars.append(json.dumps(filter))

        if self._staleness_days is not None:
            ts_key = _TIMESTAMP_KEYS[self._table]
            where_clauses.append("(metadata->>%s)::date >= CURRENT_DATE - (%s * INTERVAL '1 day')")
            query_vars.extend([ts_key, self._staleness_days])

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        query_sql = (
            f"SELECT document, metadata FROM {self._table} {where_sql}ORDER BY embedding <-> %s LIMIT %s"
        ).encode()
        query_vars.extend([vec_str, k])

        rows = self._vector_db.simple_query(query_sql, tuple(query_vars))
        documents = [Document(page_content=row[0], metadata=row[1] or {}) for row in rows]
        if selection is None:
            return documents
        return [filtered for doc in documents if (filtered := self._dated_document(doc, selection)) is not None]

    def _dated_document(self, doc: Document, selection: WeatherQuery) -> Document | None:
        if str(doc.metadata.get("id")) not in selection.station_ids:
            return None
        if selection.county and str(doc.metadata.get("county", "")).casefold() != selection.county.casefold():
            return None
        if self._table != "forecast_index":
            value = doc.metadata.get("date" if self._table == "daily_index" else "timestamp", "")
            try:
                day = date.fromisoformat(str(value)[:10])
            except ValueError:
                return None
            return doc if selection.start <= day <= selection.end else None
        # Forecast documents contain several dated rows; do not send out-of-range rows to the model.
        lines = doc.page_content.splitlines()
        header_end = next((i + 1 for i, line in enumerate(lines) if line.startswith("| ---")), 0)
        kept, days = [], set()
        for line in lines[header_end:]:
            try:
                day = date.fromisoformat(line.split("|")[1].strip()[:10])
            except (ValueError, IndexError):
                continue
            if selection.start <= day <= selection.end:
                kept.append(line)
                days.add(day.isoformat())
        if not kept:
            return None
        metadata = {key: value for key, value in doc.metadata.items() if key not in ("date", "timestamp")}
        metadata["dates"] = sorted(days)
        return Document(page_content="\n".join(lines[:header_end] + kept), metadata=metadata)

    # @warnings.deprecated("not supported for this project.")
    def from_texts(
        self,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict] | None = None,
        *args,
        ids: list[str] | None = None,
        **kwargs,
    ) -> VectorStore:
        """Interface requires this for compatibility, we do not need though! Do not implement."""
        raise NotImplementedError
