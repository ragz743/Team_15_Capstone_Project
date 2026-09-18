"""Check the indexing entry point and embedding contract brought in from main."""

import runpy
from unittest.mock import MagicMock

from backend.model_factory import ModelFactory
from backend.models import embedding_openrouter


def test_index_module_runs_all_loaders(monkeypatch):
    """The module command dispatches indexing without calling a source or provider."""
    embedding = MagicMock()
    monkeypatch.setattr(ModelFactory, "load_from_models_yaml", lambda: (embedding, MagicMock()))
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    loaders = []
    for module, name in [
        ("daily_loader", "DailyLoader"),
        ("live_loader", "LiveLoader"),
        ("forecast_loader", "ForecastLoader"),
    ]:
        loader = MagicMock()
        loaders.append(loader)
        monkeypatch.setattr(f"backend.loaders.{module}.{name}", loader)
    runpy.run_module("scripts.index", run_name="__main__")
    for loader in loaders:
        loader.assert_called_once_with(embedding)
        loader.return_value.index.assert_called_once_with()


def test_embedding_requests_numeric_vectors(monkeypatch):
    """OpenRouter receives the explicit float encoding expected by the indexer."""
    client = MagicMock()
    monkeypatch.setattr(embedding_openrouter, "OpenAIEmbeddings", client)
    embedding_openrouter.EmbeddingOpenRouter("fixture-embedding")
    assert client.call_args.kwargs["model_kwargs"]["encoding_format"] == "float"
