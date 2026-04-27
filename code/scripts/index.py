"""Script for running an index operation manually."""

import dotenv
from backend.loaders.daily_loader import DailyLoader


def main() -> None:
    """Manual indexing script entry point."""
    dotenv.load_dotenv()

    loader = DailyLoader()
    docs = loader.load()
    for doc in docs:
        print(f"{doc.page_content}\n{doc.metadata}")

    pass
