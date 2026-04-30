"""Chatbot wrapper for a local llama.cpp server (OpenAI-compatible API)."""

from typing import override

from backend.models._chatbot_base import _BaseChatbot
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class ChatbotLocal(_BaseChatbot):
    """Factory compatible wrapper for a locally hosted llama.cpp server."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of ChatbotLocal."""
        model: str = kwargs.pop("model")
        base_url: str = kwargs.pop("base_url")
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=SecretStr("local"),  # llama.cpp server does not validate the key
            **kwargs,
        )

    @override
    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages to the local model and return the response."""
        response = self._model.invoke(messages)
        match response.content:
            case str(msg):
                return msg
            case [*parts]:
                return "\n".join(str(p) for p in parts)
        return str(response.content)
