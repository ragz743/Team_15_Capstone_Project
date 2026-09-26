"""A Wrapper for the langchain ChatOpenRouter class to be instantiated by the model factory."""

import json
import os

from backend.models._chatbot_base import _BaseChatbot
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openrouter import ChatOpenRouter


def _required_schema(value):
    """Require explicit nullable fields instead of accepting silently omitted search constraints."""
    if isinstance(value, list):
        return [_required_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _required_schema(item) for key, item in value.items() if key != "default"}
    if result.get("type") == "object":
        result["required"] = list(result.get("properties", {}))
        result["additionalProperties"] = False
    return result


class ChatbotOpenRouter(_BaseChatbot):
    """Factory compatible ChatOpenRouter wrapper."""

    def __init__(self, kwargs) -> None:
        """Create an instance of the ChatbotOpenRouter."""
        model: str = kwargs.pop("model")
        self._model = ChatOpenRouter(
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),  # type: ignore (can't get SecretStr type)
            **kwargs,
        )
        if kwargs.get("max_retries") == 0:
            # This LangChain version leaves retry_config UNSET for zero retries.
            # The SDK interprets UNSET as its long default backoff, not disabled.
            self._model.client.sdk_configuration.retry_config = None

    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        response = self._model.invoke(messages)

        all_responses: str = ""
        match response.content:
            case [msgs]:
                if isinstance(msgs, str):
                    all_responses = "\n".join(msgs)
                else:
                    # TODO (Any): figure out what kind of responses return a dict
                    # is this handling ok or are we missing out on info?
                    all_responses = "\n".join([str(v) for v in msgs.values()])

            case str(msg):  # must be string
                all_responses = msg

        return all_responses

    def invoke_json(self, instructions: str, payload: dict, schema: dict) -> str:
        """Use the configured provider's structured output with no model or provider fallback."""
        response = self._model.invoke(
            [SystemMessage(content=instructions), HumanMessage(content=json.dumps(payload, default=str))],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("title", "result"),
                    "strict": True,
                    "schema": _required_schema(schema),
                },
            },
            provider={"require_parameters": True, "allow_fallbacks": False},
        )
        if not isinstance(response.content, str):
            raise ValueError("Structured model response must be JSON text")
        return response.content
