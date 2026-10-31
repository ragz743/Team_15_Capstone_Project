"""The vector store wrapper class."""

import json

from backend.databases.pgvector import PgVectorConnection
from backend.models._embedding_base import _BaseEmbedding
from backend.station_catalog import StationCatalog
from backend.weather_query import WeatherQuery
from backend.weather_records import dated_document
from backend.weather_search import FILTERABLE_KEYS, search_predicates
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from psycopg import sql


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
        if key not in FILTERABLE_KEYS:
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

    def station_catalog(self, tables: tuple[str, ...] | None = None) -> StationCatalog:
        """Share this connection with the station lookup repository."""
        return StationCatalog(self._vector_db, tables=tables if tables is not None else (self._table,))

    def similarity_search(
        self, query: str, k: int = 4, filter: dict | None = None, *, selection: WeatherQuery | None = None, **kwargs
    ) -> list[Document]:
        """Filter by source and date before ranking weather documents."""
        if not 1 <= k <= 100:
            raise ValueError("Search limit must be between 1 and 100")
        where_sql, values = search_predicates(self._table, selection, filter, self._staleness_days)
        query_vec, _ = self._embedding_model.embed_document(Document(page_content=query))
        values.extend(["[" + ",".join(str(value) for value in query_vec) + "]", k])
        query_sql = (
            f"SELECT document, metadata FROM {self._table} {where_sql}ORDER BY embedding <-> %s LIMIT %s"
        ).encode()
        rows = self._vector_db.simple_query(query_sql, tuple(values))
        documents = [Document(page_content=row[0], metadata=row[1] or {}) for row in rows]
        if selection is None:
            return documents
        return [filtered for doc in documents if (filtered := dated_document(doc, self._table, selection)) is not None]

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
