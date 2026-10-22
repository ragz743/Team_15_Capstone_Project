"""Offline tests for the loader base class behavior."""

from __future__ import annotations

from backend.loaders._loader_base import _BaseLoader
from langchain_core.documents import Document


class FakeLoader(_BaseLoader):
    """Concrete loader exercising the base index pipeline."""

    def __init__(self) -> None:
        """Initialize test data without loading production model config."""
        self._embedding_model = object()
        self.stored: list[Document] | None = None

    def _load(self) -> list[Document]:
        """Return deterministic loaded documents."""
        return [Document(page_content="loaded")]

    def _store(self, docs: list[Document]) -> list[str]:
        """Capture documents and return deterministic identifiers."""
        self.stored = docs
        return ["stored-1"]


def test_loader_base_initializes_embedding_from_model_factory(monkeypatch) -> None:
    """Load the configured embedding model during base initialization."""
    embedding = object()
    monkeypatch.setattr(
        "backend.loaders._loader_base.ModelFactory.load_from_models_yaml",
        lambda: (embedding, object()),
    )
    loader = object.__new__(FakeLoader)
    _BaseLoader.__init__(loader)

    assert loader._embedding_model is embedding


def test_loader_index_loads_then_stores_documents() -> None:
    """Return storage identifiers from the base load/store pipeline."""
    loader = FakeLoader()

    assert loader.index() == ["stored-1"]
    assert loader.stored == [Document(page_content="loaded")]
