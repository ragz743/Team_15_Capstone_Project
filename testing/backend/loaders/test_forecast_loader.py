"""Tests for backend.loaders.forecast_loader functions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import mysql.connector
import pytest
from backend.loaders._common import MetadataQueryResult
from backend.loaders.forecast_loader import (
    FallbackForecastQueryResult,
    ForecastLoader,
    PrimaryForecastQueryResult,
)
from langchain_core.documents import Document


class FakeAWNForecastConnection:
    """Fake primary forecast DB connection."""

    def __init__(self, query_results: list[tuple] | None = None, raise_error: bool = False) -> None:
        """Initialize mock primary forecast connection."""
        self.query_results = query_results or []
        self.raise_error = raise_error
        self.queries: list[str] = []

    def __enter__(self) -> FakeAWNForecastConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def simple_query(self, query: str, params: tuple) -> list[tuple]:
        """Execute mock query or raise an error if configured."""
        if self.raise_error:
            raise mysql.connector.Error("Table not found")
        self.queries.append(query)
        return self.query_results


class FakeAWNFallbackConnection:
    """Fake fallback forecast DB connection."""

    def __init__(self, query_results: list[tuple] | None = None, raise_error: bool = False) -> None:
        """Initialize mock fallback forecast connection."""
        self.query_results = query_results or []
        self.raise_error = raise_error
        self.queries: list[str] = []

    def __enter__(self) -> FakeAWNFallbackConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def simple_query(self, query: str, params: tuple) -> list[tuple]:
        """Execute mock fallback query or raise an error if configured."""
        if self.raise_error:
            raise mysql.connector.Error("Fallback table not found")
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


def test_primary_forecast_query_result_from_tuple() -> None:
    """Check converting tuple into PrimaryForecastQueryResult."""
    tstamp = datetime(2026, 9, 16, 12, 0, 0)
    row = (tstamp, 72.5, 450, 65.0)

    result = PrimaryForecastQueryResult.from_tuple(row)

    assert result.forecast_time == "2026-09-16 12:00:00"
    assert result.air_temp == 72.5
    assert result.solar_rad == 450
    assert result.soil_temp_8in == 65.0


def test_fallback_forecast_query_result_from_tuple() -> None:
    """Check converting tuple into FallbackForecastQueryResult."""
    tstamp = datetime(2026, 9, 16, 12, 0, 0)
    row = (tstamp, 70.0, 40.0, 5.5, 180.0, 0.0)

    result = FallbackForecastQueryResult.from_tuple(row)

    assert result.forecast_time == "2026-09-16 12:00:00"
    assert result.air_temp == 70.0
    assert result.rel_humidity == 40.0
    assert result.wind_speed == 5.5
    assert result.wind_dir == 180.0
    assert result.precip == 0.0


def test_query_station_current_forecast_primary_success(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check querying from primary forecast database when available."""
    tstamp = datetime(2026, 9, 16, 12, 0, 0)
    primary_conn = FakeAWNForecastConnection([(tstamp, 72.0, 500, 60.0)])
    fallback_conn = FakeAWNFallbackConnection()

    monkeypatch.setattr(
        "backend.loaders.forecast_loader.AWNForecastDatabaseConnection",
        lambda: primary_conn,
    )
    monkeypatch.setattr(
        "backend.loaders.forecast_loader.AWNForecastFallbackDatabaseConnection",
        lambda: fallback_conn,
    )

    loader = ForecastLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    results = loader._query_station_current_forecast([sample_metadata])

    assert len(results) == 1
    meta, rows, units = results[0]
    assert meta.unit_id == sample_metadata.unit_id
    assert len(rows) == 1
    assert isinstance(rows[0], PrimaryForecastQueryResult)
    assert units == PrimaryForecastQueryResult.get_units()
    assert f"fcst_{sample_metadata.unit_id}_{loader._year}" in primary_conn.queries[0]
    assert len(fallback_conn.queries) == 0


def test_query_station_current_forecast_fallback_on_primary_error(
    monkeypatch, sample_metadata: MetadataQueryResult
) -> None:
    """Check fallback to secondary forecast database when primary raises mysql.connector.Error."""
    tstamp = datetime(2026, 9, 16, 12, 0, 0)
    primary_conn = FakeAWNForecastConnection(raise_error=True)
    fallback_conn = FakeAWNFallbackConnection([(tstamp, 68.0, 45.0, 4.0, 90.0, 0.0)])

    monkeypatch.setattr(
        "backend.loaders.forecast_loader.AWNForecastDatabaseConnection",
        lambda: primary_conn,
    )
    monkeypatch.setattr(
        "backend.loaders.forecast_loader.AWNForecastFallbackDatabaseConnection",
        lambda: fallback_conn,
    )

    loader = ForecastLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    results = loader._query_station_current_forecast([sample_metadata])

    assert len(results) == 1
    meta, rows, units = results[0]
    assert meta.unit_id == sample_metadata.unit_id
    assert len(rows) == 1
    assert isinstance(rows[0], FallbackForecastQueryResult)
    assert units == FallbackForecastQueryResult.get_units()
    assert f"FROM forecast{sample_metadata.unit_id}" in fallback_conn.queries[0]


def test_load_builds_documents_correctly(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check _load creates documents with table formatted text and initial forecast timestamp."""
    forecast_row = PrimaryForecastQueryResult(
        forecast_time="2026-09-16 12:00:00",
        air_temp=75.0,
        solar_rad=600,
        soil_temp_8in=62.0,
    )

    monkeypatch.setattr(
        "backend.loaders._common.query_stations",
        lambda: [sample_metadata],
    )
    monkeypatch.setattr(
        ForecastLoader,
        "_query_station_current_forecast",
        lambda self, stations: [(sample_metadata, [forecast_row], PrimaryForecastQueryResult.get_units())],
    )

    loader = ForecastLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    docs = loader._load()

    assert len(docs) == 1
    doc = docs[0]
    assert f"Station: {sample_metadata.station} (ID: {sample_metadata.unit_id})" in doc.page_content
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
    """Check _store correctly embeds and registers documents with PgVector using station ID."""
    fake_pg_conn = FakePgVectorConnection()
    monkeypatch.setattr(
        "backend.loaders.forecast_loader.PgVectorConnection",
        lambda: fake_pg_conn,
    )

    doc = Document(
        page_content="Station: Pullman\n\n| Forecast |",
        metadata={"id": "67", "station": "Pullman"},
    )

    loader = ForecastLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    ids = loader._store([doc])

    assert ids == ["67"]
    assert len(fake_pg_conn.inserted_records) == 1

    query, params = fake_pg_conn.inserted_records[0]
    station_id, vec, content, meta_json = params
    assert station_id == "67"
    assert vec == [0.1, 0.2, 0.3]
    assert content == doc.page_content
    assert json.loads(meta_json) == {"id": "67", "station": "Pullman"}
