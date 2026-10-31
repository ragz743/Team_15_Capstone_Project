"""The base class for a chatbot model."""

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class _BaseChatbot(ABC):
    """The chatbot model base class."""

    model_name: str

    @abstractmethod
    async def ainvoke(self, messages: list[str]) -> str:
        """Asynchronously send messages to the model and return its response."""
        raise NotImplementedError

    async def astream(self, messages: list[str]) -> AsyncIterator[str]:
        """Asynchronously stream the response in text chunks; defaults to a single chunk."""
        yield await self.ainvoke(messages)

    def invoke(self, messages: list[str]) -> str:
        """Invoke the model synchronously for backward compatibility.

        Async callers should use ``await ainvoke(...)``. This adapter is intended
        only for synchronous entry points and refuses to nest event loops.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ainvoke(messages))

        msg = "invoke() cannot run inside an event loop; use 'await ainvoke(...)' instead"
        raise RuntimeError(msg)

    def invoke_json(self, instructions: str, payload: dict, schema: dict) -> str:
        """Provide a JSON contract for local/test models that do not offer constrained decoding."""
        prompt = instructions + "\nSchema:\n" + json.dumps(schema)
        prompt += "\nInput JSON:\n" + json.dumps(payload, ensure_ascii=False, default=str)
        return self.invoke([prompt])

    @staticmethod
    def _content_to_str(content: str | list) -> str:
        """Flatten a langchain message content (str or list of parts) into a single string."""
        match content:
            case str(msg):
                return msg
            case [*parts]:
                return "\n".join(p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in parts)
        return str(content)
