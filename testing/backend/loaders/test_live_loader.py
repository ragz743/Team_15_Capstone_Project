"""Tests for backend.loaders.live_loader functions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from backend.loaders._common import MetadataQueryResult
from backend.loaders.live_loader import LiveLoader, LiveQueryResult
from langchain_core.documents import Document


class FakeAWNConnection:
    """Fake AWN database connection for testing queries against station tables."""

    def __init__(self, query_results: list[tuple]) -> None:
        """Initialize mock connection with query results."""
        self.query_results = query_results
        self.queries: list[str] = []

    def __enter__(self) -> FakeAWNConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def simple_query(self, query: str, params: tuple) -> list[tuple]:
        """Execute mock query and log query string."""
        self.queries.append(query)
        return self.query_results


class FakePgVectorConnection:
    """Fake PgVector connection recording inserted parameters."""

    def __init__(self) -> None:
        """Initialize mock vector connection."""
        self.inserted_records: list[tuple[bytes, tuple[Any, ...]]] = []

    def __enter__(self) -> FakePgVectorConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def insert(self, query: bytes, params: tuple[Any, ...]) -> str:
        """Record mock vector insert operation."""
        self.inserted_records.append((query, params))
        return str(params[0])


class FakeEmbeddingModel:
    """Fake embedding model returning deterministic mock embeddings."""

    def embed_documents(self, docs: list[Document]) -> list[tuple[list[float], Document]]:
        """Return deterministic dummy embeddings for test documents."""
        return [([0.1, 0.2, 0.3], doc) for doc in docs]


@pytest.fixture
def sample_metadata() -> MetadataQueryResult:
    """Return a sample station metadata object."""
    return MetadataQueryResult(
        unit_id="67",
        station="Pullman",
        county="Whitman",
        state="WA",
        station_lat="46.73",
        station_lng="-117.18",
        air_temp=True,
        rel_humidity=True,
        precip=True,
        wind_speed=True,
        wind_dir=True,
    )


def test_live_query_result_from_tuple_valid() -> None:
    """Check converting tuple with datetime into LiveQueryResult."""
    now = datetime(2026, 9, 16, 14, 30, 0)
    row = (now, 75.5, 45.0, 0.0, 5.2, 180.0)

    result = LiveQueryResult.from_tuple(row)

    assert result.timestamp == "2026-09-16 14:30:00"
    assert result.air_temp == 75.5
    assert result.rel_humidity == 45.0
    assert result.precipitation == 0.0
    assert result.wind_speed == 5.2
    assert result.wind_dir == 180.0


def test_live_query_result_from_dict_valid() -> None:
    """Check converting dictionary into LiveQueryResult."""
    now = datetime(2026, 9, 16, 14, 30, 0)
    data = {
        "TSTAMP": now,
        "AIR_TEMP": 68.2,
        "REL_HUMIDITY": 50.0,
        "PRECIP": 0.1,
        "WIND_SP": 3.4,
        "WIND_DIR": 90.0,
    }

    result = LiveQueryResult.from_dict(data)

    assert result.timestamp == "2026-09-16 14:30:00"
    assert result.air_temp == 68.2
    assert result.wind_speed == 3.4


def test_query_station_most_recent(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check dynamic SQL construction and fetching latest station readings."""
    now = datetime(2026, 9, 16, 12, 0, 0)
    fake_conn = FakeAWNConnection([(now, 70.0, 40.0, 0.0, 4.5, 200.0)])
    monkeypatch.setattr(
        "backend.loaders.live_loader.AWNDatabaseConnection",
        lambda: fake_conn,
    )

    loader = LiveLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    results = loader._query_station_most_recent([sample_metadata])

    assert len(results) == 1
    meta, live = results[0]
    assert meta.unit_id == sample_metadata.unit_id
    assert live.air_temp == 70.0
    assert live.timestamp == "2026-09-16 12:00:00"
    assert f"FROM station{sample_metadata.unit_id}" in fake_conn.queries[0]
    assert "ORDER BY TSTAMP DESC" in fake_conn.queries[0]


def test_load_builds_documents_correctly(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check _load creates LangChain Documents with expected markdown and metadata."""
    live_record = LiveQueryResult(
        timestamp="2026-09-16 12:00:00",
        air_temp=72.0,
        rel_humidity=45.0,
        precipitation=0.0,
        wind_speed=6.0,
        wind_dir=180.0,
    )

    monkeypatch.setattr(
        "backend.loaders._common.query_stations",
        lambda: [sample_metadata],
    )
    monkeypatch.setattr(
        LiveLoader,
        "_query_station_most_recent",
        lambda self, stations: [(sample_metadata, live_record)],
    )

    loader = LiveLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    docs = loader._load()

    assert len(docs) == 1
    doc = docs[0]
    assert f"Station: {sample_metadata.station} (ID: {sample_metadata.unit_id})" in doc.page_content
    assert "| air_temp in F |" in doc.page_content
    assert doc.metadata == {
        "id": sample_metadata.unit_id,
        "station": sample_metadata.station,
        "timestamp": "2026-09-16 12:00:00",
        "county": "Whitman",
        "state": "WA",
        "latitude": "46.73",
        "longitude": "-117.18",
    }


def test_store_embeds_and_persists_documents(monkeypatch) -> None:
    """Check _store invokes embedding model and writes JSON metadata to PgVector."""
    fake_pg_conn = FakePgVectorConnection()
    monkeypatch.setattr(
        "backend.loaders.live_loader.PgVectorConnection",
        lambda: fake_pg_conn,
    )

    doc = Document(
        page_content="Station: Pullman Test Station\n\n| Data |",
        metadata={"id": "300001", "station": "Pullman Test Station"},
    )

    loader = LiveLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    ids = loader._store([doc])

    assert ids == ["300001"]
    assert len(fake_pg_conn.inserted_records) == 1

    query, params = fake_pg_conn.inserted_records[0]
    unit_id, vec, content, meta_json = params
    assert unit_id == "300001"
    assert vec == [0.1, 0.2, 0.3]
    assert content == doc.page_content
    assert json.loads(meta_json) == {"id": "300001", "station": "Pullman Test Station"}
