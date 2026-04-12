"""The base class for a chatbot model."""

from abc import ABC, abstractmethod


class _BaseChatbot(ABC):
    """The chatbot model base class."""

    @abstractmethod
    def _placeholder(self) -> object:
        # TODO (Any): Add abstract methods, what does every chatbot need to do?
        raise NotImplementedError
