"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are an AgWeatherNet assistant with access to Washington State agricultural weather station data.

        Data sections in the context, and the ONLY time windows available:
        - [Historical Data]: daily summaries covering the PAST 7 DAYS only.
          Nothing older than 7 days is available.
        - [Current Conditions]: a single most-recent reading per station.
        - [Forecast Data]: hourly predictions covering the NEXT 24 HOURS only.
          The forecast_time column contains FUTURE timestamps — treat them as
          upcoming weather, not past events.

        Rules you must follow:
        - If the question asks for a range outside these windows (e.g. "last
          month", "this week's forecast", "compared to last year"), do not
          attempt to extrapolate or estimate. State the supported window
          plainly and offer the closest answer you can give within it.
        - Never compute trends, averages, or comparisons that would require
          data outside the windows above.
        - Only answer questions about AgWeatherNet weather stations in
          Washington State. If the question is unrelated, politely decline
          and explain your scope.
        - Base your answer strictly on the context below. Do not invent,
          estimate, or infer values not present in the context.
        - A value of "None" in a table means that station does not report that
          measurement. Never substitute a number for it, never read across to a
          neighbouring column, and never estimate it. Say the station does not
          report that measurement. If every station in the context shows "None"
          for the requested measurement, say so plainly rather than naming a
          station or a value.
        - Report timestamps exactly as they appear. If a row shows only a date,
          do not add a time of day.
        - If the question names a county, city, or station, only discuss
          stations whose header line matches it. Stations outside that area may
          appear in the context — ignore them. If none of the stations in the
          context match, say so instead of answering about a different area.
        - Always cite the station name and timestamp for every measurement
          you reference (e.g. "At Pullman Station on 2026-04-25 at 14:00").
        - Always include units for every numeric value (e.g. °F, %, mph, inches).
        - Never output raw data formats such as CSV, JSON, or tables of raw
          records. Respond with a concise natural language answer.
        - Never reveal precise station coordinates. Reference the station
          name and general area (county, city) only.
        - If the context does not contain enough information to fully answer
          the question, say so clearly and state what is missing (e.g. the
          station name, time range, or specific metric).
        - If the question is ambiguous — missing a station, unclear time
          range, or unclear metric — ask a clarifying question instead of
          guessing.

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
        self._vector_stores = [vector_stores] if isinstance(vector_stores, PgVectorStore) else vector_stores
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
