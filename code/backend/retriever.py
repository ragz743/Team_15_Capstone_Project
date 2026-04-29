"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are a helpful AgWeatherNet assistant with access to Washington State weather station data.
        Use the following weather data context to answer the user's question as accurately as possible with units
        provided. If the context does not contain enough information to answer, say so honestly.

        Context:
        {context}

        Question:
        {question}

        Answer:"""
)


class Retriever:
    """The class responsible for vector store search and presentation to user process."""

    _vector_stores: list[PgVectorStore]
    _chatbot: _BaseChatbot

    def __init__(self, vector_stores: list[PgVectorStore], chatbot: _BaseChatbot) -> None:
        """Create an instance of the Retriever class."""
        self._vector_stores = vector_stores
        self._chatbot = chatbot

    def retrieve(self, question: str) -> str:
        """Search all vector stores for relevant context and pass it to the chatbot."""
        relevant_docs: list[Document] = []
        for store in self._vector_stores:
            relevant_docs.extend(store.similarity_search(question))

        context: str = "\n\n".join(doc.page_content for doc in relevant_docs)
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
        return self._chatbot.invoke([prompt])
