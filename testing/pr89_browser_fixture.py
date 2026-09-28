"""Browser fixture for map selection without database or provider requests."""

import json
from contextlib import asynccontextmanager

from backend import api
from backend.models._chatbot_base import _BaseChatbot
from backend.retriever import Retriever
from weather_fixtures import intent_json, weather_document, weather_stores


class FixtureChatbot(_BaseChatbot):
    """Return an explicit test interpretation followed by a fixed weather answer."""

    def invoke(self, messages: list[str]) -> str:
        """Separate interpretation from answer calls without classifying natural language."""
        if "\nPayload:\n" in messages[0]:
            question = json.loads(messages[0].split("\nPayload:\n")[1])["question"]
            return intent_json(question=question)
        return "The nearby Pullman source recorded 72 F on September 9, 2026."


@asynccontextmanager
async def fixture_lifespan(app):
    """Install controlled records instead of opening external connections."""
    stores = weather_stores()
    stores[0].similarity_search.return_value = [weather_document()]
    api._retriever = Retriever(stores, FixtureChatbot())
    api._chatbot_model_name = "local fixture"
    yield


app = api.app
app.router.lifespan_context = fixture_lifespan
