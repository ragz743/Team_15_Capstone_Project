"""Tests for code.backend.workflow."""

import logging
from time import perf_counter_ns
from typing import Iterator

import dotenv
import pytest
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.workflow.workflow import ChatbotWorkflow

_CONVERSATION_LOGGER_NAME = "testing.chatbot_conversations"
_CONVERSATION_LOG_FILE = "chatbot_conversations.md"


@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


@pytest.fixture(scope="module")
def conversation_logger() -> Iterator[logging.Logger]:
    """Write chatbot conversation transcripts to a dedicated log file."""
    logger = logging.getLogger(_CONVERSATION_LOGGER_NAME)
    previous_level = logger.level
    previous_propagate = logger.propagate
    handler = logging.FileHandler(_CONVERSATION_LOG_FILE, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@pytest.fixture
def workflow() -> Iterator[ChatbotWorkflow]:
    """Create a new instance of the chatbot workflow."""
    chatbot = ChatbotWorkflow(debug=True)
    try:
        yield chatbot  # give chatbot to test which may fail
    finally:
        chatbot.close()  # always cleanup, even on exception


@pytest.mark.optional
@pytest.mark.parametrize(
    ("user_input", "coords", "county"),
    [
        ("How's the frost risk looking for my sweet cherries this week?", (46.7319, -117.1510), "whitman"),
        ("How much rain did we get yesterday?", (46.7319, -117.1510), "whitman"),
        ("How's frost looking?", (46.7319, -117.1510), "whitman"),
        ("What was the high temperature yesterday?", (46.7319, -117.1510), "whitman"),
        ("Should I irrigate my grapes tomorrow?", (46.7319, -117.1510), "whitman"),
        ("Any pest risks for apples right now?", (46.7319, -117.1510), "whitman"),
        ("What's the 7-day weather outlook?", (46.7319, -117.1510), "whitman"),
        ("How's the cattle comfort index today?", (46.7319, -117.1510), "whitman"),
        ("When should I spray my cherries?", (46.7319, -117.1510), "whitman"),
    ],
)
def test_chatbot_workflow(
    workflow: ChatbotWorkflow,
    conversation_logger: logging.Logger,
    user_input: str,
    coords: tuple[float, float],
    county: str,
) -> None:
    """Test the chatbot workflow end to end."""
    start_time_ns = perf_counter_ns()
    response = workflow.run(
        user_input,
        location_coord=coords,
        county=county,
    )
    elapsed_sec = (perf_counter_ns() - start_time_ns) / 1_000_000_000

    conversation_logger.info(
        "### **Grower**: %s\n\n### **Chatbot ('%s' responded in %.3f sec)**:\n\n%s\n\n",
        user_input,
        workflow.workflow_chat_model.model_name,
        elapsed_sec,
        response,
    )


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
