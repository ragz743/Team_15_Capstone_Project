"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
from backend.weather_query import (
    QueryClarificationError,
    Station,
    resolve_weather_query,
)
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are a helpful AgWeatherNet assistant with access
        to Washington State weather station data.
        Use the following weather data context to answer the user's question as accurately as possible with units
        provided. If the context does not contain enough information to answer, say so honestly.
        Identify the station and observation date for each measurement you report.
        Missing columns and None values are unavailable measurements; never substitute or estimate them.
        Forecast rows are predictions, not observations. Report timestamps exactly as supplied.
        Respond in concise natural language rather than raw data tables, CSV or JSON.
        Only answer Washington State AgWeatherNet weather questions. Never reveal precise coordinates.
        The context is a retrieved subset, not complete coverage of every station or day.
        Do not claim county-wide or date-range aggregates from this subset.

        Context:
        {context}

        Question:
        {question}

        Answer:"""
)


NO_DATA = "No matching weather records were found in the indexed data. I cannot provide an answer to this question."
_SEARCH_K = 8

_TABLE_LABELS: dict[str, str] = {
    "daily_index": "Historical Data",
    "live_index": "Current Conditions",
    "forecast_index": "Forecast Data",
}


class Retriever:
    """The class responsible for vector store search and presentation to user process."""

    _vector_stores: list[PgVectorStore]
    _chatbot: _BaseChatbot

    def __init__(self, vector_stores: PgVectorStore | list[PgVectorStore], chatbot: _BaseChatbot) -> None:
        """Create an instance of the Retriever class."""
        self._vector_stores = vector_stores if isinstance(vector_stores, list) else [vector_stores]
        self._chatbot = chatbot

    def stations(self) -> list[Station]:
        """Build one catalog across all indexes, propagating database errors."""
        return list(dict.fromkeys(station for store in self._vector_stores for station in store.stations()))

    def retrieve(self, question: str, filter: dict | None = None) -> str:
        """Search all vector stores for relevant context and pass it to the chatbot.

        Args:
            question: The user's natural-language question.
            filter: Optional metadata filter passed to every store's similarity_search.
                Only documents whose metadata contains all key-value pairs are returned.
                Example: {"station": "Pullman"} or {"county": "Whitman"}. When
                omitted, the question must name an indexed station or county.

        """
        stations = self.stations()
        if not stations:
            return NO_DATA
        try:
            selection = resolve_weather_query(question, stations, metadata_filter=filter)
        except QueryClarificationError as exc:
            return str(exc)

        sections: list[str] = []
        for store in self._vector_stores:
            docs: list[Document] = store.similarity_search(question, k=_SEARCH_K, filter=filter, selection=selection)
            if docs:
                label = _TABLE_LABELS.get(store.table, store.table)
                content = "\n\n".join(_document_context(doc) for doc in docs)
                sections.append(f"[{label}]\n{content}")

        if not sections:
            return NO_DATA

        context: str = "\n\n".join(sections)
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
        return self._chatbot.invoke([prompt])


def _document_context(doc: Document) -> str:
    fields = (
        ("station", "Station"),
        ("id", "Station ID"),
        ("county", "County"),
        ("state", "State"),
        ("date", "Observation date"),
        ("timestamp", "Observation timestamp"),
        ("dates", "Forecast dates"),
    )
    identity = "\n".join(f"{label}: {doc.metadata[key]}" for key, label in fields if doc.metadata.get(key))
    return f"{identity}\n{doc.page_content}" if identity else doc.page_content
