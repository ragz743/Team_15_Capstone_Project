"""Script for running a retrieval query manually."""

import sys

import dotenv
from backend.model_factory import ModelFactory
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore


def main() -> None:
    """Manual retrieval script entry point."""
    dotenv.load_dotenv()
    embedding_model, chatbot_model = ModelFactory.load_from_models_yaml()

    store = PgVectorStore(embedding_model)
    retriever = Retriever(store, chatbot_model)

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter your question: ")
    response = retriever.retrieve(question)
    print(response)


if __name__ == "__main__":
    main()
