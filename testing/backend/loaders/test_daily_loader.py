"""Tests for backend.loaders.daily_loader functions."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from backend.loaders._common import MetadataQueryResult
from backend.loaders.daily_loader import DailyLoader, DailyQueryResult
from langchain_core.documents import Document


class FakeAWNDailyConnection:
    """Fake AWN daily database connection recording queries."""

    def __init__(self, query_results: list[tuple]) -> None:
        """Initialize mock daily connection with preset results."""
        self.query_results = query_results
        self.queries: list[str] = []
        self.params: list[tuple] = []

    def __enter__(self) -> FakeAWNDailyConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def simple_query(self, query: str, params: tuple) -> list[tuple]:
        """Execute mock query and log query string and parameters."""
        self.queries.append(query)
        self.params.append(params)
        return self.query_results


class FakePgVectorConnection:
    """Fake PgVector connection recording inserted parameters."""

    def __init__(self) -> None:
        """Initialize mock vector storage record list."""
        self.inserted_records: list[tuple[bytes, tuple[Any, ...]]] = []

    def __enter__(self) -> FakePgVectorConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def insert(self, query: bytes, params: tuple[Any, ...]) -> str:
        """Record mock insert execution."""
        self.inserted_records.append((query, params))
        return "1"


class FakeEmbeddingModel:
    """Fake embedding model returning deterministic mock embeddings."""

    def embed_documents(self, docs: list[Document]) -> list[tuple[list[float], Document]]:
        """Return deterministic dummy embeddings for provided documents."""
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


def test_daily_query_result_from_tuple_valid() -> None:
    """Check converting tuple into DailyQueryResult."""
    day = date(2026, 9, 16)
    row = (day, Decimal("65.5"), Decimal("50.0"), Decimal("0.05"), Decimal("4.2"), Decimal("190.0"))

    result = DailyQueryResult.from_tuple(row)

    assert result.date == "2026-09-16"
    assert result.avg_air_temp == Decimal("65.5")
    assert result.avg_humidity == Decimal("50.0")
    assert result.sum_precip == Decimal("0.05")
    assert result.avg_wind_sp == Decimal("4.2")
    assert result.avg_wind_dir == Decimal("190.0")


def test_daily_query_result_from_dict_valid() -> None:
    """Check converting dictionary into DailyQueryResult."""
    day = datetime(2026, 9, 16)
    data = {
        "JULDATE": day,
        "AVG_AIR_TEMP": Decimal("68.0"),
        "AVG_HUMIDITY": Decimal("55.0"),
        "SUM_PRECIP": Decimal("0.0"),
        "AVG_WIND_SP": Decimal("3.1"),
        "AVG_WIND_DIR": Decimal("180.0"),
    }

    result = DailyQueryResult.from_dict(data)

    assert result.date == "2026-09-16"
    assert result.avg_air_temp == Decimal("68.0")
    assert result.sum_precip == Decimal("0.0")


def test_query_station_daily(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check SQL construction and week-ago filtering for daily query."""
    day = datetime(2026, 9, 16)
    fake_conn = FakeAWNDailyConnection([(day, 65.0, 50.0, 0.0, 4.0, 180.0)])
    monkeypatch.setattr(
        "backend.loaders.daily_loader.AWNDailyDatabaseConnection",
        lambda: fake_conn,
    )

    loader = DailyLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    results = loader._query_station_daily([sample_metadata])

    assert len(results) == 1
    meta, daily = results[0]
    assert meta.unit_id == sample_metadata.unit_id
    assert daily.date == "2026-09-16"

    # Query checks
    assert f"FROM station{sample_metadata.unit_id}daily" in fake_conn.queries[0]
    assert "WHERE JULDATE >= %s" in fake_conn.queries[0]
    expected_since = (date.today() - timedelta(weeks=1)).strftime("%Y-%m-%d")
    assert fake_conn.params[0] == (expected_since,)


def test_load_builds_documents_correctly(monkeypatch, sample_metadata: MetadataQueryResult) -> None:
    """Check _load builds LangChain Document with table markdown and daily metadata."""
    daily_record = DailyQueryResult(
        date="2026-09-16",
        avg_air_temp=Decimal("65.5"),
        avg_humidity=Decimal("50.0"),
        sum_precip=Decimal("0.0"),
        avg_wind_sp=Decimal("5.0"),
        avg_wind_dir=Decimal("180.0"),
    )

    monkeypatch.setattr(
        "backend.loaders._common.query_stations",
        lambda: [sample_metadata],
    )
    monkeypatch.setattr(
        DailyLoader,
        "_query_station_daily",
        lambda self, stations: [(sample_metadata, daily_record)],
    )

    loader = DailyLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    docs = loader._load()

    assert len(docs) == 1
    doc = docs[0]
    assert f"Station: {sample_metadata.station} (ID: {sample_metadata.unit_id})" in doc.page_content
    assert doc.metadata == {
        "id": sample_metadata.unit_id,
        "date": "2026-09-16",
        "station": sample_metadata.station,
        "county": "Whitman",
        "state": "WA",
        "latitude": "46.73",
        "longitude": "-117.18",
    }


def test_store_embeds_and_persists_documents(monkeypatch) -> None:
    """Check _store persists documents into daily_index table."""
    fake_pg_conn = FakePgVectorConnection()
    monkeypatch.setattr(
        "backend.loaders.daily_loader.PgVectorConnection",
        lambda: fake_pg_conn,
    )

    doc = Document(
        page_content="Station: Pullman\n\n| Daily Data |",
        metadata={"id": "67", "date": "2026-09-16"},
    )

    loader = DailyLoader(embedding_model=FakeEmbeddingModel())  # type: ignore[arg-type]
    ids = loader._store([doc])

    assert ids == ["1"]
    assert len(fake_pg_conn.inserted_records) == 1

    query, params = fake_pg_conn.inserted_records[0]
    vec, content, meta_json = params
    assert vec == [0.1, 0.2, 0.3]
    assert content == doc.page_content
    assert json.loads(meta_json) == {"id": "67", "date": "2026-09-16"}
