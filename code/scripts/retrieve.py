"""Script for running a retrieval query manually."""

import argparse
from datetime import date

import dotenv
from backend.model_factory import ModelFactory
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore


def _is_stale() -> bool:
    """Return True if live_index has no record dated today."""
    try:
        from backend.databases.pgvector import PgVectorConnection

        conn = PgVectorConnection()
        rows = list(
            conn.simple_query(
                b"SELECT COUNT(*) FROM live_index WHERE metadata->>'timestamp' = %s",
                (date.today().isoformat(),),
            )
        )
        conn.conn.close()
        return int(rows[0][0]) == 0
    except Exception:
        return False


def _refresh(embedding_model) -> None:
    """Run all loaders to pull fresh data from AgWeatherNet into pgvector."""
    from backend.loaders import daily_loader, forecast_loader, live_loader

    print("Index data is stale — refreshing from AgWeatherNet...")
    for loader_class in [daily_loader.DailyLoader, live_loader.LiveLoader, forecast_loader.ForecastLoader]:
        loader_class(embedding_model).index()
    print("Refresh complete.")


def main() -> None:
    """Manual retrieval script entry point."""
    parser = argparse.ArgumentParser(description="Run a RAG retrieval query.")
    parser.add_argument("question", nargs="*", help="Question to ask")
    parser.add_argument("--no-refresh", action="store_true", help="Skip the automatic freshness check")
    args = parser.parse_args()

    dotenv.load_dotenv()
    embedding_model, chatbot_model = ModelFactory.load_from_models_yaml()

    if not args.no_refresh and _is_stale():
        try:
            _refresh(embedding_model)
        except Exception as e:
            print(f"Warning: index refresh failed ({e}). Proceeding with existing data.")

    stores = [
        PgVectorStore(embedding_model, table="daily_index"),
        PgVectorStore(embedding_model, table="live_index", staleness_days=30),
        PgVectorStore(embedding_model, table="forecast_index"),
    ]
    retriever = Retriever(stores, chatbot_model)

    question = " ".join(args.question) if args.question else input("Enter your question: ")
    response = retriever.retrieve(question)
    print(response)


if __name__ == "__main__":
    main()
