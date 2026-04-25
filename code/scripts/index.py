"""Script for running an index operation manually."""

import dotenv
from backend.loaders import daily_loader, forecast_loader, live_loader
from backend.model_factory import ModelFactory


def main() -> None:
    """Manual indexing script entry point."""
    dotenv.load_dotenv()
    embedding_model, _ = ModelFactory.load_from_models_yaml()

    for loader_class in [daily_loader.DailyLoader, live_loader.LiveLoader, forecast_loader.ForecastLoader]:
        loader = loader_class(embedding_model)
        loader.index()

    pass
