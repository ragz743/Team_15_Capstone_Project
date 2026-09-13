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


_TABLE_LABELS: dict[str, str] = {
    "daily_index": "Historical Data",
    "live_index": "Current Conditions",
    "forecast_index": "Forecast Data",
}


class Retriever:
    """The class responsible for vector store search and presentation to user process."""

    # Retriever now holds a list[PgVectorStore]
    _vector_stores: list[PgVectorStore]
    _chatbot: _BaseChatbot

    def __init__(self, vector_stores: PgVectorStore | list[PgVectorStore], chatbot: _BaseChatbot) -> None:
        """Create an instance of the Retriever class."""
        self._vector_stores = [vector_stores] if isinstance(vector_stores, PgVectorStore) else vector_stores
        self._chatbot = chatbot

    # Queries _vector_stores and assembles a labeled context ([Historical Data],
    # [Current Conditions], [Forecast Data]) so the LLM knows what type of data
    # it's reading
    def retrieve(self, question: str) -> str:
        """Search all vector stores for relevant context and pass it to the chatbot."""
        sections: list[str] = []
        for store in self._vector_stores:
            docs: list[Document] = store.similarity_search(question)
            if docs:
                label = _TABLE_LABELS.get(store.table, store.table)
                content = "\n\n".join(doc.page_content for doc in docs)
                sections.append(f"[{label}]\n{content}")

        context: str = "\n\n".join(sections)
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
        return self._chatbot.invoke([prompt])
