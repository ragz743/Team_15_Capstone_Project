"""Controlled interpretation and source records for local retrieval tests."""

import json
import math
from unittest.mock import MagicMock

from backend.vector_store import PgVectorStore
from backend.weather_query import QueryClarificationError, RequestedPoint, Station
from langchain_core.documents import Document

POINT = RequestedPoint(latitude=46.73, longitude=-117.18)
STATION = Station("1", "Pullman", "Whitman", "46.731", "117.181", "WA")


def intent_json(**changes) -> str:
    """Return a valid provider response with explicit overrides."""
    return json.dumps(
        {
            "action": "query",
            "location": "selected",
            "data_kind": "both",
            "start": "2026-09-09",
            "end": "2026-09-09",
            "question": "Temperature here on 2026-09-09?",
            "message": "",
            **changes,
        }
    )


def weather_stores():
    """Create independently observable indexes with a shared source identity."""
    stores = []
    for table in ("daily_index", "live_index", "forecast_index"):
        store = MagicMock(spec=PgVectorStore)
        store.table = table
        store.station_catalog.return_value.resolve.side_effect = _fixture_station
        store.similarity_search.return_value = []
        stores.append(store)
    return stores


def _fixture_station(point: RequestedPoint) -> Station:
    """Keep the controlled source limited to nearby map points."""
    latitude, longitude = map(math.radians, (point.latitude, point.longitude))
    source_latitude, source_longitude = map(math.radians, (46.731, -117.181))
    distance = 12742.0176 * math.asin(
        math.sqrt(
            math.sin((latitude - source_latitude) / 2) ** 2
            + math.cos(latitude) * math.cos(source_latitude) * math.sin((longitude - source_longitude) / 2) ** 2
        )
    )
    if distance > 50:
        raise QueryClarificationError("No indexed weather source is within 50 km of that point.")
    return STATION


def weather_document() -> Document:
    """Supply a real forecast table plus dated observation metadata."""
    return Document(
        page_content="| timestamp | temperature in F |\n| --- | --- |\n| 2026-09-09 12:00:00 | 72 |",
        metadata={
            "id": "1",
            "station": "Pullman",
            "county": "Whitman",
            "date": "2026-09-09",
            "timestamp": "2026-09-09 12:00:00",
            "dates": ["2026-09-09"],
        },
    )
