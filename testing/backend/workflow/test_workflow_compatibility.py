"""Keep streamed answers and saved-chat results compatible after merging the workflows."""

import asyncio
from unittest.mock import MagicMock

import pytest
from backend.workflow.workflow import ChatbotWorkflow
from workflow_fixture import make_graph


@pytest.mark.parametrize("empty", [False, True])
def test_stream_returns_observations_and_missing_data(monkeypatch, empty):
    """The streaming entry point must return the same evidence outcome as saved chats."""
    runtime = make_graph(monkeypatch)
    runtime.graph._nearest_station_search = MagicMock(return_value=1)
    if empty:
        runtime.cursor.fetchall.return_value = []

    async def collect():
        return [chunk async for chunk in runtime.graph.run("Temperature?", (46.7, -117.1), "Whitman")]

    try:
        answer = "".join(asyncio.run(collect()))
    finally:
        runtime.graph.close()

    assert ("No matching weather records" if empty else "70.25") in answer
    assert runtime.model.invoke.call_count == (1 if empty else 2)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_result_accepts_positional_location(monkeypatch, asynchronous):
    """Keep the original location arguments working for collected results."""
    runtime = make_graph(monkeypatch)
    runtime.graph._nearest_station_search = MagicMock(return_value=1)
    try:
        if asynchronous:
            answer = asyncio.run(runtime.graph.arun_result("Temperature?", (46.7, -117.1), "Whitman"))
        else:
            answer = runtime.graph.run_result("Temperature?", (46.7, -117.1), "Whitman")
    finally:
        runtime.graph.close()

    assert "70.25" in answer.reply
    runtime.graph._nearest_station_search.assert_called_once_with((46.7, -117.1), "Whitman")


def test_schema_cache_is_scoped_to_connection_and_table(monkeypatch):
    """Retain main's per-connection cache without mixing forecast partitions."""
    runtime = make_graph(monkeypatch)
    other = MagicMock()
    other.query_schema.return_value = []
    try:
        ChatbotWorkflow._weather_schema(runtime.graph, runtime.database, "fcst_1_2026")
        ChatbotWorkflow._weather_schema(runtime.graph, runtime.database, "fcst_1_2026")
        ChatbotWorkflow._weather_schema(runtime.graph, runtime.database, "fcst_1_2027")
        ChatbotWorkflow._weather_schema(runtime.graph, other, "fcst_1_2026")
    finally:
        runtime.graph.close()

    assert [call.args for call in runtime.database.query_schema.call_args_list] == [
        ("fcst_1_2026",),
        ("fcst_1_2027",),
    ]
    other.query_schema.assert_called_once_with("fcst_1_2026")
