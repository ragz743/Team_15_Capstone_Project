"""The base class for a chatbot model."""

from abc import ABC, abstractmethod


class _BaseChatbot(ABC):
    """The chatbot model base class."""

    @abstractmethod
    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        # TODO (Any): Add abstract methods, what does every chatbot need to do?
        raise NotImplementedError
