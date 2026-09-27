"""Tests for code.backend.workflow."""

import dotenv
import pytest
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.workflow.workflow import ChatbotWorkflow


@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


@pytest.fixture
def workflow() -> ChatbotWorkflow:
    """Create a new instance of the chatbot workflow."""
    return ChatbotWorkflow(debug=True)


@pytest.mark.optional
@pytest.mark.parametrize(
    ("user_input", "coords", "county"),
    [
        ("How’s the frost risk looking for my sweet cherries this week?", (46.7319, -117.1510), "whitman"),
        ("How much rain did we get yesterday?", (46.7319, -117.1510), "whitman"),
        ("How’s frost looking?", (46.7319, -117.1510), "whitman"),
        ("What was the high temperature yesterday?", (46.7319, -117.1510), "whitman"),
        ("Should I irrigate my grapes tomorrow?", (46.7319, -117.1510), "whitman"),
        ("Any pest risks for apples right now?", (46.7319, -117.1510), "whitman"),
        ("What’s the 7-day weather outlook?", (46.7319, -117.1510), "whitman"),
        ("How’s the cattle comfort index today?", (46.7319, -117.1510), "whitman"),
        ("When should I spray my cherries?", (46.7319, -117.1510), "whitman"),
    ],
)
def test_chatbot_workflow(
    workflow: ChatbotWorkflow,
    user_input: str,
    coords: tuple[float, float],
    county: str,
) -> None:
    """Test the chatbot workflow end to end."""
    response = workflow.run(
        user_input,
        location_coord=coords,
        county=county,
    )

    print(f"response:\n\n{response}")


@pytest.mark.parametrize(
    ("location_coords", "county", "expected_station_id"),
    [
        ((46.7319, -117.1510), "whitman", 100093),
        ((47.3936, -120.4299), "chelan", 330037),
        ((48.7319, -122.5026), "whatcom", 330061),
    ],
)
def test_nearest_station_search(location_coords: tuple[float, float], county: str, expected_station_id) -> None:
    """Search for the nearest station in the database for each coordinate/county pair."""
    workflow = object.__new__(ChatbotWorkflow)
    workflow.current_db = AWNDatabaseConnection()
    try:
        actual_station_id = workflow._nearest_station_search(location_coords, county)
    finally:
        workflow.current_db.conn.disconnect()

    assert actual_station_id == expected_station_id
