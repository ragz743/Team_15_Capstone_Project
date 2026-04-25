"""Script for running an index operation manually."""

import dotenv
from backend.loaders.forecast_loader import ForecastLoader
from backend.model_factory import ModelFactory
from backend.vector_store import PgVectorStore


def main() -> None:
    """Manual indexing script entry point."""
    dotenv.load_dotenv()
    embedding_model, _ = ModelFactory.load_from_models_yaml()

    loader = ForecastLoader()
    vector_store = PgVectorStore(embedding_model)
    vector_store.load_and_store(loader)

    pass
