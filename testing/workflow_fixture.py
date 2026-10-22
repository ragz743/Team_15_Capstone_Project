"""Controlled model replies and source records for LangGraph integration tests."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import backend.workflow.workflow as graph_module
from backend.databases._awn_connection_base import SchemaQueryResult
from backend.workflow.workflow import ChatbotWorkflow, ClassifierChatbot


def make_graph(monkeypatch):
    """Run Gavin's graph with controlled provider replies and weather records."""
    database = MagicMock()
    database.format_table_name.return_value = "station1daily"
    database.query_schema.return_value = [
        SchemaQueryResult("JULDATE", "date", "YES", "", ""),
        SchemaQueryResult("AVG_AIR_TEMP", "decimal", "YES", "", ""),
        SchemaQueryResult("AIR_TEMP_MODIFIED_BY", "varchar", "YES", "", ""),
    ]
    cursor = database.conn.cursor.return_value.__enter__.return_value
    cursor.description = [("JULDATE",), ("AVG_AIR_TEMP",)]
    cursor.fetchall.return_value = [(datetime(2026, 9, 29).date(), Decimal("70.25"))]
    for name in ("AWNDatabaseConnection", "AWNDailyDatabaseConnection", "AWNForecastDatabaseConnection"):
        monkeypatch.setattr(graph_module, name, lambda **kwargs: database)
    model = MagicMock()
    model.invoke.side_effect = [
        "SELECT JULDATE, AVG_AIR_TEMP FROM station1daily WHERE JULDATE = '2026-09-29'",
        "At Pullman on 2026-09-29 the average temperature was 70.25 F.",
    ]
    classifier = MagicMock()
    classifier.invoke_json.return_value = (
        '{"sub_queries":[{"query_type":"historical_weather","reworded_query":"Temperature on 2026-09-29"}]}'
    )
    graph = ChatbotWorkflow(chat_model=model, classifier=ClassifierChatbot(classifier))
    return SimpleNamespace(graph=graph, model=model, classifier=classifier, cursor=cursor, database=database)
