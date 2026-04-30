"""Tests for the model_factory class."""

import dotenv
import pytest
from backend.model_factory import ModelFactory
from langchain_core.documents import Document


# Call loadenv function once this test file
@pytest.fixture(scope="module", autouse=True)
def load_environment_vars() -> None:
    """Load environment variables used for db connection."""
    dotenv.load_dotenv()


def test_model_factory_load_from_models_yaml() -> None:
    """Validate the the model factory can create classes from models.yaml and the api key is valid."""
    embedding_model, chatbot_model = ModelFactory.load_from_models_yaml()

    doc = Document(
        page_content="hello world!",
        metadata={},
    )

    assert embedding_model.embed_document(doc), "failed to connect and embed document"
    assert chatbot_model.invoke([doc.page_content]), "failed to connect to chatbot and get response"
