"""The base class for a chatbot model."""

from abc import ABC, abstractmethod


class _BaseChatbot(ABC):
    """The chatbot model base class."""

    @abstractmethod
    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        # TODO (Any): Add abstract methods, what does every chatbot need to do?
        raise NotImplementedError

    @staticmethod
    def _content_to_str(content: str | list) -> str:
        """Flatten a langchain message content (str or list of parts) into a single string."""
        match content:
            case str(msg):
                return msg
            case [*parts]:
                return "\n".join(p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in parts)
        return str(content)
