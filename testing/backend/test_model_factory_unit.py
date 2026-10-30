"""Edge-case tests for model configuration loading."""

from __future__ import annotations

import pytest
from backend.model_factory import ModelFactory


class FakeModel:
    """Factory-compatible model double."""

    def __init__(self, kwargs: dict) -> None:
        """Capture constructor parameters."""
        self.kwargs = kwargs


def write_models_file(tmp_path, monkeypatch, content: str) -> None:
    """Write a temporary configuration and use its directory as the project root."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "models.yaml").write_text(content, encoding="utf-8")


def test_load_from_models_yaml_raises_when_file_is_missing(tmp_path, monkeypatch) -> None:
    """Report a missing project model configuration."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="unable to locate models.yaml"):
        ModelFactory.load_from_models_yaml()


def test_load_from_models_yaml_requires_models_mapping(tmp_path, monkeypatch) -> None:
    """Reject YAML without the required models section."""
    write_models_file(tmp_path, monkeypatch, "other: value\n")

    with pytest.raises(ValueError, match="does not match expected format"):
        ModelFactory.load_from_models_yaml()


def test_load_from_models_yaml_builds_models_from_dynamic_classes(tmp_path, monkeypatch) -> None:
    """Import configured classes and pass each model its own keyword mapping."""
    write_models_file(
        tmp_path,
        monkeypatch,
        """
models:
  embedding:
    class_file: embedding_impl.py
    class: Embedding
    kwargs:
      model: embed-model
  chatbot:
    class_file: chatbot_impl
    class: Chatbot
    kwargs:
      model: chat-model
""",
    )
    imported: list[tuple[str, str]] = []

    def import_class(module: str, class_name: str):
        imported.append((module, class_name))
        return FakeModel

    monkeypatch.setattr(ModelFactory, "_import_class", staticmethod(import_class))

    embedding, chatbot = ModelFactory.load_from_models_yaml()

    assert imported == [("embedding_impl", "Embedding"), ("chatbot_impl", "Chatbot")]
    assert vars(embedding)["kwargs"] == {"model": "embed-model"}
    assert vars(chatbot)["kwargs"] == {"model": "chat-model"}


@pytest.mark.parametrize(
    "content",
    [
        "models:\n  extra:\n    class_file: extra.py\n",
        "models:\n  embedding:\n    class_file: embedding.py\n    class: Embedding\n    kwargs: {}\n",
        "models:\n  chatbot:\n    class_file: chatbot.py\n    class: Chatbot\n    kwargs: {}\n",
    ],
)
def test_load_from_models_yaml_rejects_unrecognized_or_incomplete_entries(tmp_path, monkeypatch, content: str) -> None:
    """Reject unsupported entries and configurations that omit either required model."""
    write_models_file(tmp_path, monkeypatch, content)
    monkeypatch.setattr(ModelFactory, "_import_class", staticmethod(lambda module, name: FakeModel))

    with pytest.raises(ValueError):
        ModelFactory.load_from_models_yaml()


def test_import_class_resolves_class_from_backend_models(monkeypatch) -> None:
    """Resolve and return a class attribute from its configured model module."""
    sentinel = object()
    imported: list[str] = []

    class Module:
        Target = sentinel

    monkeypatch.setattr(
        "backend.model_factory.importlib.import_module",
        lambda name: imported.append(name) or Module,
    )

    assert ModelFactory._import_class("example", "Target") is sentinel
    assert imported == ["backend.models.example"]
