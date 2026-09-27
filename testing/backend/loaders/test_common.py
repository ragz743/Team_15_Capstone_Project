"""Tests for the loaders._common functions."""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

import pytest
from backend.loaders import _common


class FakeAWNConnection:
    """Mock database connection for testing query_stations without a real DB."""

    def __init__(self, query_results: list[tuple]) -> None:
        """Initialize fake connection with predetermined query results."""
        self.query_results = query_results
        self.last_query: str | None = None
        self.last_params: tuple | None = None

    def __enter__(self) -> FakeAWNConnection:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

    def simple_query(self, query: str, params: tuple) -> list[tuple]:
        """Execute a mock simple query and record parameters."""
        self.last_query = query
        self.last_params = params
        return self.query_results


class SampleMeasurement(NamedTuple):
    """Container for sample weather measurement test data."""

    timestamp: str
    air_temp: float | None
    precip: float | None


def test_to_markdown_table() -> None:
    """Test the formatting of the to_markdown_table function is correct."""
    actual = [
        _common.MetadataQueryResult(
            "67",
            "Pullman",
            "Whitman",
            "WA",
            "123.4",
            "567.8",
            True,
            True,
            True,
            True,
            True,
        ),
        _common.MetadataQueryResult(
            "10001",
            "Quincy",
            "Grant",
            "WA",
            "100",
            "200",
            False,
            False,
            False,
            False,
            False,
        ),
    ]
    units = ["", "", "", "", "degrees", "degrees", "", "", "", "", ""]
    expected = (
        "| unit_id | station | county | state | station_lat in degrees | station_lng in degrees |"
        " air_temp | rel_humidity | precip | wind_speed | wind_dir |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 67 | Pullman | Whitman | WA | 123.4 | 567.8 | True | True | True | True | True |\n"
        "| 10001 | Quincy | Grant | WA | 100 | 200 | False | False | False | False | False |\n"
    )

    actual_table = _common.to_markdown_table(actual, units)
    assert actual_table == expected, f"found \n{actual_table},\nexpected\n{expected}"


def test_to_markdown_table_drops_all_none_columns() -> None:
    """Check that columns containing only None values across all rows are omitted."""
    rows = [
        SampleMeasurement("2026-09-16 12:00:00", 72.4, None),
        SampleMeasurement("2026-09-16 13:00:00", 74.8, None),
    ]
    units = ["", "F", "inches"]

    table = _common.to_markdown_table(rows, units)

    assert "air_temp in F" in table
    assert "precip" not in table
    assert "72.4" in table
    assert "74.8" in table


def test_format_cell_rounds_floats_and_decimals() -> None:
    """Verify _format_cell formats floats and Decimals to one decimal place."""
    assert _common._format_cell(12.3456) == "12.3"
    assert _common._format_cell(Decimal("89.99")) == "90.0"
    assert _common._format_cell("2026-09-16") == "2026-09-16"
    assert _common._format_cell(True) == "True"


def test_metadata_query_result_from_tuple_valid() -> None:
    """Check converting DB tuple into MetadataQueryResult and mapping 'Y'/'N' to bool."""
    raw_row = (
        "67",
        "Pullman",
        "Whitman",
        "WA",
        "46.73",
        "-117.18",
        "Y",
        "Y",
        "N",
        "Y",
        "N",
    )

    result = _common.MetadataQueryResult.from_tuple(raw_row)

    assert result.unit_id == "67"
    assert result.station == "Pullman"
    assert result.air_temp is True
    assert result.precip is False
    assert result.wind_speed is True
    assert result.wind_dir is False


def test_metadata_query_result_from_tuple_invalid_raises_error() -> None:
    """Check that a tuple with wrong length/types raises a ValueError."""
    with pytest.raises(ValueError, match="unrecognized tuple structure"):
        _common.MetadataQueryResult.from_tuple(("67", "Pullman"))


def test_query_stations(monkeypatch) -> None:
    """Check query_stations executes the expected query and parses returned rows."""
    fake_rows = [
        ("67", "Pullman", "Whitman", "WA", "46.73", "-117.18", "Y", "Y", "Y", "Y", "Y"),
        ("10001", "Quincy", "Douglas", "WA", "47.23", "-119.85", "Y", "N", "N", "N", "N"),
    ]
    fake_conn = FakeAWNConnection(fake_rows)
    monkeypatch.setattr(_common, "AWNDatabaseConnection", lambda: fake_conn)

    stations = _common.query_stations()

    assert len(stations) == 2
    assert stations[0].station == "Pullman"
    assert stations[0].air_temp is True
    assert stations[1].station == "Quincy"
    assert stations[1].rel_humidity is False
    assert fake_conn.last_query is not None
    assert "WHERE" in fake_conn.last_query
    assert 'ACTIVE_STATION = "Y"' in fake_conn.last_query
