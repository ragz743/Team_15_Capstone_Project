"""The class responsible for creating llm model classes."""

from backend.models._chatbot_base import _BaseChatbot
from backend.models._embedding_base import _BaseEmbedding


class ModelFactory:
    """The class that creates model classes."""

    @staticmethod
    def load_embedding_model() -> _BaseEmbedding:
        """Load an embedding model type and return an instance of it."""
        raise NotImplementedError

    @staticmethod
    def load_chatbot_model() -> _BaseChatbot:
        """Load a chatbot model type and return an instance of it."""
        raise NotImplementedError
