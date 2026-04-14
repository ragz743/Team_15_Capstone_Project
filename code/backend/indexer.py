"""Code for the indexing controller class, Indexer."""

from backend.loaders._loader_base import _BaseLoader
from backend.model_factory import ModelFactory
from backend.splitter import Splitter
from backend.vector_store import PgVectorStore
from langchain_core.documents import Document


class Indexer:
    """Manages the indexing process."""

    _vector_store: PgVectorStore
    _loader: _BaseLoader
    _splitter: Splitter

    def __init__(
        self,
        loader: _BaseLoader,
    ):
        """Create an instance of the Indexer class."""
        self._loader = loader
        self._splitter = Splitter()
        self._vector_store = PgVectorStore(ModelFactory.load_embedding_model())

    def index(self) -> None:
        """Index all records extracted by the loader and processed by the splitter into the vectorstore."""
        docs: list[Document] = self._loader.load()
        chunks: list[Document] = self._splitter.split(docs)
        self._vector_store.add_documents(chunks)
