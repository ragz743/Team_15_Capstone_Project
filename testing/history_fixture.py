"""Scripted model replies for wiring tests; these do not measure language understanding."""

import json

from backend.models._chatbot_base import _BaseChatbot


class FixtureHistoryModel(_BaseChatbot):
    """Keep existing database/browser scenarios offline through the real history service."""

    def invoke(self, messages):
        """Handle only the explicit fixture scenarios and return structured model replies."""
        payload = json.loads(messages[0].split("\nInput JSON:\n", 1)[1])
        if "excerpts" in payload:
            return json.dumps(
                {
                    "statements": [
                        {"text": "Your saved discussion included this question and reply.", "refs": [entry["ref"]]}
                        for entry in payload["excerpts"][:2]
                    ]
                }
            )
        question = payload["message"]
        if question == "What did we discuss last time?":
            return '{"action":"recall","scope":"previous"}'
        if question == "Using our last conversation, what about humidity?":
            return '{"action":"reuse","scope":"previous","weather_question":"What about humidity?"}'
        if question == "Can you bring back that frost chat?":
            return '{"action":"recall","terms":["frost","freezing"]}'
        return '{"action":"weather"}'


def structured_mock(model):
    """Preserve mock call assertions while using the base model's structured prompt contract."""
    model.invoke_json.side_effect = lambda instructions, payload, schema: _BaseChatbot.invoke_json(
        model, instructions, payload, schema
    )
    return model
