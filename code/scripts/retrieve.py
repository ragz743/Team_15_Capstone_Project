"""Script for running a retrieval query manually."""

import argparse

import dotenv
from backend.model_factory import ModelFactory
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore


def main() -> None:
    """Manual retrieval script entry point."""
    parser = argparse.ArgumentParser(description="Run a RAG retrieval query.")
    parser.add_argument("question", nargs="*", help="Question to ask")
    args = parser.parse_args()

    dotenv.load_dotenv()
    embedding_model, chatbot_model = ModelFactory.load_from_models_yaml()

    # CLI now creates all three stores and passes them to Retriever class.
    # The --table flag is removed.
    stores = [
        PgVectorStore(embedding_model, table="daily_index"),
        PgVectorStore(embedding_model, table="live_index"),
        PgVectorStore(embedding_model, table="forecast_index"),
    ]
    retriever = Retriever(stores, chatbot_model)

    question = " ".join(args.question) if args.question else input("Enter your question: ")
    response = retriever.retrieve(question)
    print(response)


if __name__ == "__main__":
    main()
