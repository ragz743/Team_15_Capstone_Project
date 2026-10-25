"""Chatbot wrapper for a local llama.cpp server (OpenAI-compatible API)."""

from collections.abc import AsyncIterator
from typing import override

from backend.models._chatbot_base import _BaseChatbot
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class ChatbotLocal(_BaseChatbot):
    """Factory compatible wrapper for a locally hosted llama.cpp server."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of ChatbotLocal."""
        self.model_name: str = kwargs.pop("model")
        base_url: str = kwargs.pop("base_url")
        self._model = ChatOpenAI(
            model=self.model_name,
            base_url=base_url,
            api_key=SecretStr("local"),  # llama.cpp server does not validate the key
            **kwargs,
        )

    @override
    async def astream(self, messages: list[str]) -> AsyncIterator[str]:
        """Asynchronously stream the local model response in text chunks."""
        async for chunk in self._model.astream(messages):
            if isinstance(chunk.content, str):
                if chunk.content:
                    yield chunk.content
            else:
                for part in chunk.content:
                    text = part if isinstance(part, str) else part.get("text", "")
                    if text:
                        yield text

    @override
    async def ainvoke(self, messages: list[str]) -> str:
        """Asynchronously send messages to the local model and return the response."""
        response = await self._model.ainvoke(messages)
        match response.content:
            case str(msg):
                return msg
            case [*parts]:
                return "\n".join(str(p) for p in parts)
        return str(response.content)
