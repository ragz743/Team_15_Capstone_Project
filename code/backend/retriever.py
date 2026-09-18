"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
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


# Documents pulled per index. The measurement tables are near-identical in shape,
# so a small k can rank the wrong stations above the one actually asked about.
_SEARCH_K = 8

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
        self._vector_stores = vector_stores if isinstance(vector_stores, list) else [vector_stores]
        self._chatbot = chatbot
        self._known_values: dict[str, list[str]] | None = None

    def _load_known_values(self) -> dict[str, list[str]]:
        """Collect the station and county names present across all stores.

        Longest names are matched first so "Pullman NE" wins over "Pullman".
        """
        if self._known_values is not None:
            return self._known_values

        values: dict[str, set[str]] = {"station": set(), "county": set()}
        for store in self._vector_stores:
            for key in values:
                values[key].update(store.distinct_metadata_values(key))

        self._known_values = {key: sorted(vals, key=len, reverse=True) for key, vals in values.items()}
        return self._known_values

    def _detect_filter(self, question: str) -> dict | None:
        """Derive a metadata filter from a station or county named in the question.

        A named station is a stronger signal than a county, so it is preferred.
        Without this, semantic search ranks near-identical measurement tables by
        embedding distance alone and can miss the very station being asked about.
        """
        asked = question.lower()
        known = self._load_known_values()
        for key in ("station", "county"):
            for value in known.get(key, []):
                if value.lower() in asked:
                    return {key: value}
        return None

    # Queries _vector_stores and assembles a labeled context ([Historical Data],
    # [Current Conditions], [Forecast Data]) so the LLM knows what type of data
    # it's reading
    def retrieve(self, question: str, filter: dict | None = None) -> str:
        """Search all vector stores for relevant context and pass it to the chatbot.

        Args:
            question: The user's natural-language question.
            filter: Optional metadata filter passed to every store's similarity_search.
                Only documents whose metadata contains all key-value pairs are returned.
                Example: {"station": "Pullman"} or {"county": "Whitman"}. When
                omitted, a filter is inferred from any station or county named in
                the question.

        """
        if filter is None:
            filter = self._detect_filter(question)

        sections: list[str] = []
        for store in self._vector_stores:
            docs: list[Document] = store.similarity_search(question, k=_SEARCH_K, filter=filter)
            if docs:
                label = _TABLE_LABELS.get(store.table, store.table)
                content = "\n\n".join(doc.page_content for doc in docs)
                sections.append(f"[{label}]\n{content}")

        if not sections:
            return (
                "No matching weather records were found in the indexed data. "
                "I cannot provide an answer to this question."
            )

        context: str = "\n\n".join(sections)
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
        return self._chatbot.invoke([prompt])
