"""The class responsible for creating llm model classes."""

import importlib
import os
import pathlib
from typing import Callable

import yaml
from backend.models._chatbot_base import _BaseChatbot
from backend.models._embedding_base import _BaseEmbedding


class ModelFactory:
    """The class that creates model classes."""

    _models_module: str = "backend.models"

    @staticmethod
    def load_from_models_yaml() -> tuple[_BaseEmbedding, _BaseChatbot]:
        """Parse models.yaml and create both embedding and chatbot models."""
        models_yaml = pathlib.Path("models.yaml")
        if not models_yaml.exists():
            msg = "unable to locate models.yaml file in project root directory"
            raise FileNotFoundError(msg)

        config: dict[str, dict]
        with models_yaml.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)

        models: dict[object, object] | None = config.get("models")
        if models is None:
            msg = "models.yaml does not match expected format, please look at project README for details"
            raise ValueError(msg)

        embedding_model: _BaseEmbedding | None = None
        chatbot_model: _BaseChatbot | None = None
        for key, values in models.items():
            match (key, values):
                case "embedding", {
                    "class_file": python_file,
                    "class": python_class,
                    "kwargs": kwargs,
                }:
                    file_name: str = str(python_file).removesuffix(".py")
                    embedding_class = ModelFactory._import_class(file_name, python_class)
                    embedding_model = embedding_class(kwargs)
                case "chatbot", {
                    "class_file": python_file,
                    "class": python_class,
                    "kwargs": kwargs,
                }:
                    file_name: str = str(python_file).removesuffix(".py")
                    chatbot_class = ModelFactory._import_class(file_name, python_class)
                    chatbot_model = chatbot_class(kwargs)
                case _:
                    msg = f"unrecognized yaml format for'{key}' {values}, please see project README"
                    raise ValueError(msg)

        if embedding_model is None or chatbot_model is None:
            msg = f"unable to parse model.yaml config {models}"
            raise ValueError

        return embedding_model, chatbot_model

    @staticmethod
    def _import_class(python_file: str, python_class: str) -> Callable:
        model = importlib.import_module(f"{ModelFactory._models_module}.{python_file}")
        model_class = getattr(model, python_class)
        return model_class

    @staticmethod
    def load_embedding_model() -> _BaseEmbedding:
        """Load an embedding model type and return an instance of it."""
        from backend.models.embedding_openrouter import EmbeddingOpenRouter

        model_name = os.environ["EMBEDDING_MODEL"]
        return EmbeddingOpenRouter({"model": model_name})

    @staticmethod
    def load_chatbot_model() -> _BaseChatbot:
        """Load a chatbot model type and return an instance of it."""
        from backend.models.chatbot_openrouter import ChatbotOpenRouter

        return ChatbotOpenRouter({"model": os.environ["CHATBOT_MODEL"]})
