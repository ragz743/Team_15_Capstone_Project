"""Data accuracy test suite.

Run:
    pytest testing/e2e/test_data_accuracy.py -v -s --html=reports/accuracy_report.html --self-contained-html

"""

from __future__ import annotations

import json
import os
import re

import psycopg2
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"
PG_HOST = "localhost"
PG_PORT = 5432
PG_DB = "vectorstore"
PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "qwer1234")

# How much numeric difference is acceptable (in original units)
# Note: F for temp, % for humidity, inches for percip, mph for wind
TEMP_TOLERANCE = 3.0
HUMIDITY_TOLERANCE = 5.0
PRECIP_TOLERANCE = 0.1
WIND_TOLERANCE = 5.0


def _pg_connect():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB,
    )


def _is_api_ready() -> bool:
    try:
        return requests.get(f"{BASE_URL}/api/health", timeout=3).json().get("retriever_ready", False)
    except Exception:
        return False


def _has_indexed_data() -> bool:
    try:
        conn = _pg_connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM daily_index")
        row = cur.fetchone()
        conn.close()
        return row is not None and row[0] > 0
    except Exception:
        return False


def _chat(question: str) -> str:
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={"messages": [{"role": "user", "content": question}]},
        timeout=30,
    )
    assert response.status_code == 200, f"API error: {response.text}"
    return response.json()["reply"]


def _extract_numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+", text)]


def _closest_number(numbers: list[float], target: float) -> float | None:
    if not numbers:
        return None
    return min(numbers, key=lambda x: abs(x - target))


def _get_station_daily(station: str) -> dict | None:
    try:
        conn = _pg_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document, metadata
            FROM daily_index
            WHERE metadata->>'station' = %s
            ORDER BY metadata->>'date' DESC
            LIMIT 1
        """,
            (station,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"document": row[0], "metadata": json.loads(row[1])}
    except Exception:
        return None


def _get_station_live(station: str) -> dict | None:
    try:
        conn = _pg_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document, metadata
            FROm live_index
            WHERE metadata->>'station' = %s
            ORDER BY metadata->>'timestamp' DESC
            LIMIT 1
        """,
            (station,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"document": row[0], "metadata": json.loads(row[1])}
    except Exception:
        return None


def _get_station_forecast(station: str) -> dict | None:
    try:
        conn = _pg_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document, metadata
            FROM forecast_index
            WHERE metadata->>'station' = %s
            ORDER BY metadata->>'timestamp' DESC
            LIMIT 1
        """,
            (station,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"document": row[0], "metadata": json.loads(row[1])}
    except Exception:
        return None


def _parse_value_from_document(document: str, column_index: int) -> float | None:
    lines = [line.strip() for line in document.strip().split("\n") if line.strip()]
    data_lines = [line for line in lines if line.startswith("|") and "---" not in line and line.count("|") > 2]

    if len(data_lines) < 2:
        return None
    first_data_row = data_lines[1]
    cols = [c.strip() for c in first_data_row.split("|") if c.strip()]
    if column_index >= len(cols):
        return None
    try:
        return float(cols[column_index])
    except (ValueError, IndexError):
        return None


# Can add more later
KNOWN_STATIONS = ["Pullman", "Fairfield", "Sunrise", "Mansfield", "Waterville", "Green Bluff"]

api_ready = pytest.mark.skipif(not _is_api_ready(), reason="API is not running")
data_ready = pytest.mark.skipif(not _has_indexed_data(), reason="No indexed data (run: retrieve 'any question')")


# Daily data accuracy tests
@api_ready
@data_ready
@pytest.mark.parametrize("station", KNOWN_STATIONS)
def test_daily_temperature_accuracy(station: str):
    """Test accuracy of daily temperature data for a station."""
    record = _get_station_daily(station)
    if record is None:
        pytest.skip(f"No live data for station: {station}")

    actual_temp = _parse_value_from_document(record["document"], column_index=1)
    if actual_temp is None:
        pytest.skip(f"Could not parse temperature from live document for {station}")

    question = f"What is the current temperature in {station}?"
    reply = _chat(question)

    print(f"\nStation: {station}")
    print(f"DB value (live air_temp): {actual_temp}F")
    print(f"Chatbot reply: {reply}")

    numbers = _extract_numbers(reply)
    reported = _closest_number(numbers, actual_temp)

    assert reported is not None, f"No number found in reply for {station}"
    assert abs(actual_temp - reported) <= TEMP_TOLERANCE, (
        f"Live temperature mismatch for {station}: "
        f"DB={actual_temp}F, Chatbot={reported}F, "
        f"diff={abs(actual_temp - reported):.2f}F (tolerance={TEMP_TOLERANCE}F)"
    )


@api_ready
@data_ready
@pytest.mark.parametrize("station", KNOWN_STATIONS)
def test_daily_humidity_accuracy(station: str):
    """Test accuracy of daily humidity data for a station."""
    record = _get_station_daily(station)
    if record is None:
        pytest.skip(f"No daily data for station: {station}")

    actual_humidity = _parse_value_from_document(record["document"], column_index=2)
    if actual_humidity is None:
        pytest.skip(f"Could not parse humidity from document for {station}")

    question = f"What was the average humidity in {station} recently?"
    reply = _chat(question)

    print(f"\nStation: {station}")
    print(f"DB value (avg_humidity): {actual_humidity}%")
    print(f"Chatbot reply: {reply}")

    numbers = _extract_numbers(reply)
    reported = _closest_number(numbers, actual_humidity)

    assert reported is not None, f"No number found in reply for {station}"
    assert abs(actual_humidity - reported) <= HUMIDITY_TOLERANCE, (
        f"Humidity mismatch for {station}: "
        f"DB={actual_humidity}%, Chatbot={reported}%, "
        f"diff={abs(actual_humidity - reported):.2f}% (tolerance={HUMIDITY_TOLERANCE}%)"
    )


# Live data accuracy tests
@api_ready
@data_ready
@pytest.mark.parametrize("station", KNOWN_STATIONS)
def test_live_temperature_accuracy(station: str):
    """Test accuracy of live temperature data for a station."""
    record = _get_station_live(station)
    if record is None:
        pytest.skip(f"No live data for station: {station}")

    actual_temp = _parse_value_from_document(record["document"], column_index=1)
    if actual_temp is None:
        pytest.skip(f"Could not parse temperature from live document for {station}")

    question = f"What is the current temperature in {station}?"
    reply = _chat(question)

    print(f"\nStation: {station}")
    print(f"DB value (live air_temp): {actual_temp}F")
    print(f"Chatbot reply: {reply}")

    numbers = _extract_numbers(reply)
    reported = _closest_number(numbers, actual_temp)

    assert reported is not None, f"No number found in reply for {station}"
    assert abs(actual_temp - reported) <= TEMP_TOLERANCE, (
        f"Live temperature mismatch for {station}: "
        f"DB={actual_temp}F, Chatbot={reported}F, "
        f"diff={abs(actual_temp - reported):.2f}F (tolerance={TEMP_TOLERANCE}F)"
    )


# Forecast data accuracy tests
@api_ready
@data_ready
@pytest.mark.parametrize("station", KNOWN_STATIONS)
def test_forecast_temperature_accuracy(station: str):
    """Test accuracy of forecast temperature data for a station."""
    record = _get_station_forecast(station)
    if record is None:
        pytest.skip(f"No forecast data for station: {station}")

    actual_temp = _parse_value_from_document(record["document"], column_index=1)
    if actual_temp is None:
        pytest.skip(f"Could not parse temperature from forecast document for {station}")

    question = f"What is the temperature forecast for {station}?"
    reply = _chat(question)

    print(f"\nStation: {station}")
    print(f"DB value (forecast air_temp): {actual_temp}F")
    print(f"Chatbot reply: {reply}")

    numbers = _extract_numbers(reply)
    reported = _closest_number(numbers, actual_temp)

    assert reported is not None, f"No number found in reply for {station}"
    assert abs(actual_temp - reported) <= TEMP_TOLERANCE, (
        f"Forecast temperature mismatch for {station}: "
        f"DB={actual_temp}F, Chatbot={reported}F, "
        f"diff={abs(actual_temp - reported):.2f}F (tolerance={TEMP_TOLERANCE}F)"
    )
