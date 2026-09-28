"""HTTP validation for point selection and retired station filters."""

from unittest.mock import MagicMock

import backend.api as api
import pytest
from fastapi.testclient import TestClient
from weather_fixtures import POINT


@pytest.mark.parametrize(
    "fields",
    [
        {"debug": True},
        {"filter": {"id": "1"}},
        {"filter": {"station": "Pullman"}},
        {"point": {"latitude": 95, "longitude": -117}},
        {"point": {"latitude": "46.7", "longitude": -117}},
        {"point": {"latitude": 46.7, "longitude": -117, "station_id": "99"}},
    ],
)
def test_invalid_fields_are_rejected_before_retrieval(monkeypatch, fields):
    """The browser can supply a point but cannot override source selection."""
    retriever = MagicMock()
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Weather?"}],
            **fields,
        },
    )
    assert response.status_code == 422
    retriever.retrieve.assert_not_called()


def test_valid_point_reaches_retrieval(monkeypatch):
    """Keep user coordinates distinct from private source metadata."""
    retriever = MagicMock()
    retriever.retrieve.return_value = "Weather reply"
    monkeypatch.setattr(api, "_retriever", retriever)
    response = TestClient(api.app).post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Weather?"}],
            "point": POINT.model_dump(),
        },
    )
    assert response.status_code == 200
    retriever.retrieve.assert_called_once_with("Weather?", point=POINT)
