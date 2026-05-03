"""Script for running a retrieval query manually."""

import argparse

# import sys
import dotenv
from backend.model_factory import ModelFactory
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore


def main() -> None:
    """Manual retrieval script entry point."""
    parser = argparse.ArgumentParser(description="Run a RAG retrieval query.")
    parser.add_argument("--table", default="daily_index", help="Vector store table to query (default: daily_index)")
    parser.add_argument("question", nargs="*", help="Question to ask")
    args = parser.parse_args()

    dotenv.load_dotenv()
    embedding_model, chatbot_model = ModelFactory.load_from_models_yaml()

    store = PgVectorStore(embedding_model, table=args.table)
    retriever = Retriever(store, chatbot_model)

    question = " ".join(args.question) if args.question else input("Enter your question: ")
    response = retriever.retrieve(question)
    print(response)


if __name__ == "__main__":
    main()
