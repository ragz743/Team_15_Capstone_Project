"""The loader base class."""

from abc import abstractmethod
from typing import ClassVar

from backend.model_factory import ModelFactory
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document


class _BaseLoader(BaseLoader):
    """Implement the langchain BaseLoader interface but also manage the data source."""

    insert_sql: ClassVar[bytes]

    def __init__(self) -> None:
        """Create an instance of the loader class."""
        # NOTE: Need to implement, just load embedding. Doing both will have to do for now...
        self._embedding_model, _ = ModelFactory.load_from_models_yaml()

    # TODO (Any): Add the aload (async load) as another abstract method
    @abstractmethod
    def _load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        raise NotImplementedError

    @abstractmethod
    def _store(self, docs: list[Document]) -> list[str]:
        """Given a list of documents, store them in the vector store."""

    def index(self) -> list[str]:
        """Load documents, process them, and store in the vector store."""
        return self._store(self._load())
