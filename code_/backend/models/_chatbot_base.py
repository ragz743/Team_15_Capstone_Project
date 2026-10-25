"""The base class for a chatbot model."""

import asyncio
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
