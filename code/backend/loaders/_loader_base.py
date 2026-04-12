"""The loader base class."""

from abc import abstractmethod

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document


class _BaseLoader(BaseLoader):
    """Implement the langchain BaseLoader interface but also manage the data source."""

    awn_database: AWNDatabaseConnectionBase

    # TODO (Any): Add the aload (async load) as another abstract method
    @abstractmethod
    def load(self) -> list[Document]:
        """Load the data from the datasource and process into documents."""
        raise NotImplementedError
