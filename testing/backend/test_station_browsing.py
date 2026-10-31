"""Station browsing stays separate from weather generation and saved chats."""

from dataclasses import replace
from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.station_catalog import browse_stations
from backend.workflow.engine import AWNStationDirectory, LangGraphEngine
from fastapi.testclient import TestClient
from weather_fixtures import POINT, STATION


def test_nearby_ranks_stations_and_keeps_missing_coordinates_browsable():
    """Names remain selectable when distances are unavailable."""
    further = replace(STATION, id="2", name="Colfax", latitude="46.9")
    missing = replace(STATION, id="3", name="Missing point", latitude=None)
    result = browse_stations([further, missing, STATION, STATION], POINT)
    assert [station.id for station in result.stations] == ["1", "2", "3"]
    assert result.stations[0].distance_km is not None and result.stations[1].distance_km is not None
    assert result.stations[0].distance_km < result.stations[1].distance_km
    assert result.stations[2].distance_km is None
    assert result.located_count == 2
    assert "latitude" not in result.model_dump_json() and "longitude" not in result.model_dump_json()
    assert [station.name for station in browse_stations([STATION, further]).stations] == ["Colfax", STATION.name]


def test_conflicting_identities_are_excluded_and_conflicting_coordinates_are_unranked():
    """An ambiguous station ID cannot become a manual selection."""
    assert not browse_stations([STATION, replace(STATION, name="Other")]).stations
    result = browse_stations([STATION, replace(STATION, latitude="46.9")], POINT)
    assert len(result.stations) == 1 and result.stations[0].distance_km is None


def test_browsing_reuses_metadata_without_models_or_coordinate_storage(monkeypatch):
    """The nearby endpoint reads only the cached public station directory."""
    connection, model, store = MagicMock(), MagicMock(), MagicMock()
    db = connection.return_value.__enter__.return_value
    db.simple_query.return_value = [
        (STATION.id, STATION.name, STATION.county, STATION.latitude, STATION.longitude, STATION.state)
    ]
    directory = AWNStationDirectory(connection)
    monkeypatch.setattr(api, "_retriever", LangGraphEngine(model, model, directory=directory))
    monkeypatch.setattr(api, "_conversations", store)
    client = TestClient(api.app)
    assert client.get("/api/stations").status_code == 200
    response = client.post("/api/stations/nearby", json=POINT.model_dump())
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["stations"][0]["id"] == STATION.id
    assert "latitude" not in response.text and "longitude" not in response.text
    db.simple_query.assert_called_once()
    assert db.simple_query.call_args.args[0].startswith("SELECT ")
    assert "METADATA" in db.simple_query.call_args.args[0]
    assert model.mock_calls == [] and store.mock_calls == []


@pytest.mark.parametrize("latitude", [91, True, "46.7"])
def test_nearby_rejects_invalid_browser_coordinates(monkeypatch, latitude):
    """Invalid coordinates cannot reach the catalog."""
    engine = MagicMock()
    monkeypatch.setattr(api, "_retriever", engine)
    response = TestClient(api.app).post("/api/stations/nearby", json={"latitude": latitude, "longitude": -117})
    assert response.status_code == 422
    engine.station_catalog.assert_not_called()


def test_catalog_errors_do_not_expose_provider_details(monkeypatch):
    """Directory failures remain errors instead of empty station lists."""
    engine = MagicMock()
    engine.station_catalog.side_effect = RuntimeError("private database detail")
    monkeypatch.setattr(api, "_retriever", engine)
    response = TestClient(api.app).get("/api/stations")
    assert response.status_code == 502 and "private database" not in response.text
    monkeypatch.setattr(api, "_retriever", None)
    assert TestClient(api.app).get("/api/stations").status_code == 503
