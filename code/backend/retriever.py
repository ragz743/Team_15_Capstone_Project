"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are an AgWeatherNet assistant with
    access to Washington State agricultural weather
    station data.

        Rules you must follow:
        - Only answer questions about AgWeatherNet
        weather stations in Washington State. If
        the question is unrelated to AgWeatherNet
        data or Washington State weather, politely
        decline and explain your scope.
        - Base your answer strictly on the context
        below. Do not invent, estimate, or infer
        values not present in the context.
        - Always cite the station name and
        timestamp for every measurement you
        reference (e.g. "At Pullman Station on
        2026-04-25 at 14:00").
        - Always include units for every numeric
        value (e.g. °F, %, mph, inches).
        - Never output raw data formats such as
        CSV, JSON, or tables of raw records.
        Respond with a concise natural language
        answer.
        - Never reveal precise station coordinates.
        Reference the station name and general area
        (county, city) only.
        - If the context does not contain enough
        information to fully answer the question,
        say so clearly and state what is missing
        (e.g. the station name, time range, or
        specific metric).
        - If the question is ambiguous — missing a
        station, unclear time range, or unclear
        metric — ask a clarifying question instead
        of guessing.

        Context:
        {context}

        Question:
        {question}

        Answer:"""
)


class Retriever:
    """The class responsible for vector store search and presentation to user process."""

    _vector_store: PgVectorStore
    _chatbot: _BaseChatbot

    def __init__(self, vector_store: PgVectorStore, chatbot: _BaseChatbot) -> None:
        """Create an instance of the Retriever class."""
        self._vector_store = vector_store
        self._chatbot = chatbot

    def retrieve(self, question: str) -> str:
        """Search the vector store for relevant context and pass it to the chatbot."""
        # Search vector store for relevant documents
        relevant_docs: list[Document] = self._vector_store.similarity_search(question)

        # Combine document contents into a single string
        context: str = "\n\n".join(doc.page_content for doc in relevant_docs)

        # Format the prompt with context & question
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        # Pass the prompt to the chatbot and return the response
        return self._chatbot.invoke([prompt])
