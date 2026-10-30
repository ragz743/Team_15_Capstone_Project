"""Chatbot wrappers for locally hosted models (llama.cpp server, in-process llama-cpp, Ollama)."""

import pathlib
from typing import override

from backend.models._chatbot_base import _BaseChatbot
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class _LangchainChatbot(_BaseChatbot):
    """Shared invoke logic for chatbots backed by a langchain chat model."""

    _model: BaseChatModel

    @override
    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages to the local model and return the response."""
        return self._content_to_str(self._model.invoke(messages).content)


class ChatbotLocal(_LangchainChatbot):
    """Factory compatible wrapper for a llama.cpp server (OpenAI-compatible API)."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of ChatbotLocal."""
        config = dict(kwargs)
        self.model_name: str = config.pop("model")
        base_url: str = config.pop("base_url")
        self._model = ChatOpenAI(
            model=self.model_name,
            base_url=base_url,
            api_key=SecretStr("local"),  # llama.cpp server does not validate the key
            **config,
        )


class ChatbotLlamaCpp(_LangchainChatbot):
    """Factory compatible wrapper for running a GGUF model in-process with langchain-community ChatLlamaCpp."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of ChatbotLlamaCpp."""
        # imported here so the optional [local] dependencies are only needed when this class is used
        from langchain_community.chat_models import ChatLlamaCpp

        config = dict(kwargs)
        model_path: str = config.pop("model_path")
        self.model_name: str = pathlib.Path(model_path).name  # the GGUF file name identifies the model
        self._model = ChatLlamaCpp(model_path=model_path, **config)


class ChatbotOllama(_LangchainChatbot):
    """Factory compatible wrapper for a model served by Ollama with langchain-ollama ChatOllama."""

    def __init__(self, kwargs: dict) -> None:
        """Create an instance of ChatbotOllama."""
        from langchain_ollama import ChatOllama

        config = dict(kwargs)
        self.model_name: str = config.pop("model")
        self._model = ChatOllama(model=self.model_name, **config)  # base_url defaults to http://localhost:11434
