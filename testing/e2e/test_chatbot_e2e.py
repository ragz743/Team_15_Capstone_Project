"""End-to-end chatbot quality test suite.

Sends real questions to the live API and records actual responses.
Requires Docker to be running: docker compose --profile local_llm up -d

Run and generate quality report:
    pytest testing/e2e/test_chatbot_e2e.py -v --html=reports/e2e_report.html --self-contained-html
"""

from __future__ import annotations

import pytest
import requests

BASE_URL = "http://localhost:8000"


def _is_api_ready() -> bool:
    """Return True if the API is up and retriever is initialized."""
    try:
        data = requests.get(f"{BASE_URL}/api/health", timeout=3).json()
        return data.get("retriever_ready", False)
    except requests.RequestException:
        return False


def _chat(question: str) -> str:
    """Send a question to the chatbot and return the reply."""
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={"messages": [{"role": "user", "content": question}]},
        timeout=30,
    )
    assert response.status_code == 200, f"API returned {response.status_code}: {response.text}"
    return response.json()["reply"]


api_ready = pytest.mark.skipif(not _is_api_ready(), reason="API not running — start Docker first")

# Question bank
IN_SCOPE_QUESTIONS = [
    (
        "current_temp_pullman",
        "What is the current temperature in Pullman?",
        ["pullman", "temperature", "°f", "fahrenheit", "celsius", "degrees"],
        ["world cup", "capital", "i don't know"],
    ),
    (
        "current_humidity_pullman",
        "What is the current humidity in Pullman?",
        ["humidity", "pullman", "%"],
        ["world cup", "capital"],
    ),
    (
        "historical_temp_last_week",
        "What was the average temperature in Pullman last week?",
        ["pullman", "temperature", "average", "°f", "degrees", "week"],
        ["world cup", "i cannot"],
    ),
    (
        "forecast_this_week",
        "What is the weather forecast for Pullman this week?",
        ["pullman", "forecast", "temperature", "high", "low"],
        ["world cup"],
    ),
    (
        "wind_speed_pullman",
        "What is the wind speed in Pullman right now?",
        ["wind", "pullman", "mph", "speed"],
        ["world cup"],
    ),
    (
        "precipitation_pullman",
        "How much precipitation has Pullman received this month?",
        ["pullman", "precipitation", "rain", "inch", "mm"],
        ["world cup"],
    ),
]

OUT_OF_SCOPE_QUESTIONS = [
    (
        "world_cup",
        "Who won the 2024 World Cup?",
        ["don't have", "cannot answer", "only answer", "not able", "outside", "no information"],
        [],
    ),
    (
        "capital_of_france",
        "What is the capital of France?",
        ["don't have", "cannot", "only answer", "not able", "outside"],
        [],
    ),
    (
        "write_poem",
        "Write me a poem about rain.",
        ["don't have", "cannot", "only answer", "not able", "outside"],
        [],
    ),
    (
        "math_question",
        "What is 2 + 2?",
        ["don't have", "cannot", "only answer", "not able", "outside"],
        [],
    ),
]


@api_ready
@pytest.mark.parametrize(
    "test_id,question,expected,forbidden",
    IN_SCOPE_QUESTIONS,
    ids=[q[0] for q in IN_SCOPE_QUESTIONS],
)
def test_in_scope_question(request, test_id, question, expected, forbidden):
    """Chatbot should answer AWN weather questions with relevant content."""
    reply = _chat(question)
    reply_lower = reply.lower()

    # Attach Q&A to the HTML report
    request.node._report_sections = []
    extras = getattr(request.node, "extras", [])
    request.node.extras = extras

    # Log for report
    print(f"\nQ: {question}")
    print(f"A: {reply}")

    has_expected = any(kw in reply_lower for kw in expected)
    has_forbidden = any(kw in reply_lower for kw in forbidden)

    assert has_expected, f"\nQuestion: {question}\nReply: {reply}\nExpected at least one of: {expected}"
    assert not has_forbidden, (
        f"\nQuestion: {question}\nReply: {reply}\n"
        f"Forbidden phrase found: {[kw for kw in forbidden if kw in reply_lower]}"
    )


@api_ready
@pytest.mark.parametrize(
    "test_id,question,expected,forbidden",
    OUT_OF_SCOPE_QUESTIONS,
    ids=[q[0] for q in OUT_OF_SCOPE_QUESTIONS],
)
def test_out_of_scope_question(request, test_id, question, expected, forbidden):
    """Chatbot must refuse questions outside the AWN database."""
    reply = _chat(question)
    reply_lower = reply.lower()

    print(f"\nQ: {question}")
    print(f"A: {reply}")

    has_refusal = any(kw in reply_lower for kw in expected)

    assert has_refusal, (
        f"\nQuestion: {question}\nReply: {reply}\nExpected a refusal phrase, got none.\n*** HALLUCINATION DETECTED ***"
    )


@api_ready
def test_multi_turn_weather_conversation():
    """Chatbot should handle follow-up questions in a conversation."""
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "What is the current temperature in Pullman?"},
                {"role": "assistant", "content": "The current temperature in Pullman is 68°F."},
                {"role": "user", "content": "What about the humidity?"},
            ]
        },
        timeout=30,
    )

    reply = response.json()["reply"]
    print("\nFollow-up Q: What about the humidity?")
    print(f"A: {reply}")

    assert response.status_code == 200
    assert len(reply) > 0
