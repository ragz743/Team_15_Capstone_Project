"""Preserve dates used by station/date retrieval when loading observations."""

from datetime import datetime
from unittest.mock import MagicMock

from backend.loaders._common import MetadataQueryResult
from backend.loaders.forecast_loader import ForecastLoader, PrimaryForecastQueryResult
from backend.loaders.live_loader import LiveQueryResult
from pytest import MonkeyPatch


def test_live_dictionary_keeps_full_observation_timestamp() -> None:
    """Dictionary conversion must preserve the same precision as tuple conversion."""
    timestamp = datetime(2026, 9, 9, 23, 59, 30)
    observation = LiveQueryResult.from_dict({"TSTAMP": timestamp})
    assert observation.timestamp == LiveQueryResult.from_tuple((timestamp, None, None, None, None, None)).timestamp
    assert observation.timestamp == "2026-09-09 23:59:30"


def test_forecast_metadata_lists_all_observation_dates(monkeypatch: MonkeyPatch) -> None:
    """A later forecast day must be searchable even when the first row is earlier."""
    station = MetadataQueryResult("1", "Pullman", "Whitman", "WA", "0", "0", True, True, True, True, True)
    monkeypatch.setattr("backend.loaders.forecast_loader._common.query_stations", lambda: [station])
    monkeypatch.setattr(
        ForecastLoader,
        "_query_station_current_forecast",
        lambda self, stations: [
            (
                station,
                [
                    PrimaryForecastQueryResult("2026-09-09 12:00:00", 72, 100, 60),
                    PrimaryForecastQueryResult("2026-09-10 12:00:00", 85, 100, 60),
                    PrimaryForecastQueryResult("2026-09-10 13:00:00", 86, 100, 60),
                ],
                PrimaryForecastQueryResult.get_units(),
            )
        ],
    )
    docs = ForecastLoader(MagicMock())._load()
    assert docs[0].metadata["dates"] == ["2026-09-09", "2026-09-10"]
