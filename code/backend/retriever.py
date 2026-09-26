"""Code for the data retriever controller class, Retriever."""

from datetime import date

from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import ConversationContext, resolve_turn
from backend.models._chatbot_base import _BaseChatbot
from backend.vector_store import PgVectorStore
from backend.weather_query import (
    QueryClarificationError,
    Station,
    WeatherQuery,
    resolve_weather_query,
)
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

RAG_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are an AgWeatherNet assistant with access to Washington State agricultural weather station data.

        Data sections in the context:
        - [Historical Data]: daily summaries for the dates in each record.
        - [Current Conditions]: observations at the timestamps in each record.
        - [Forecast Data]: hourly predictions for the forecast dates shown.
          Treat forecast_time as the prediction time, not an observation time.

        Rules you must follow:
        - Answer only for the requested location and dates using the records
          below. If records are missing, explain the gap rather than using
          another location or time period.
        - Retrieved records are a subset and may not cover the entire requested
          county or period. Do not present a county-wide or date-range aggregate
          as complete based on this subset.
        - Never compute trends, averages, or comparisons that require data
          outside the retrieved records.
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
        self._vector_stores = [vector_stores] if isinstance(vector_stores, PgVectorStore) else vector_stores
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

        return self._answer(question, selection, filter)

    def prepare_turn(
        self, question: str, context: ConversationContext | None = None, *, today: date | None = None
    ) -> PreparedChatTurn:
        """Resolve and freeze saved weather context before calling external services."""
        stations = self.stations()
        if not stations:
            return PreparedChatTurn(
                outcome="no_data", question=question, context=context or ConversationContext(), reply=NO_DATA
            )
        turn = resolve_turn(question, stations, context, today=today)
        if turn.clarification:
            return PreparedChatTurn(
                outcome="needs_clarification", question=question, context=turn.context, reply=turn.clarification
            )
        return PreparedChatTurn(
            outcome="weather", question=turn.question, context=turn.context, selection=turn.selection
        )

    def answer_result(self, turn: PreparedChatTurn) -> AnsweredTurn:
        """Retrieve fresh weather using the accepted constraints, never saved assistant text."""
        if turn.reply is not None:
            assert turn.outcome != "weather"
            return AnsweredTurn(reply=turn.reply, outcome=turn.outcome)
        assert turn.selection is not None
        reply = self._answer(turn.question, turn.selection)
        return AnsweredTurn(reply=reply, outcome="no_data" if reply == NO_DATA else "success")

    def _answer(self, question: str, selection: WeatherQuery, filter: dict | None = None) -> str:
        sections: list[str] = []
        sources: list[str] = []
        for store in self._vector_stores:
            docs: list[Document] = store.similarity_search(question, k=_SEARCH_K, filter=filter, selection=selection)
            if docs:
                label = _TABLE_LABELS.get(store.table, store.table)
                content = "\n\n".join(_document_context(doc) for doc in docs)
                sections.append(f"[{label}]\n{content}")
                sources.extend(_source_label(doc, store.table) for doc in docs)

        if not sections:
            return NO_DATA

        context: str = "\n\n".join(sections)
        prompt: str = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
        answer = self._chatbot.invoke([prompt])
        if not answer.strip():
            return answer
        labels = "\n".join(dict.fromkeys(sources))
        return (
            answer
            + "\n\nRetrieved records:\n"
            + labels
            + "\nThese records may not cover every station or day you requested."
        )


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


def _source_label(doc: Document, table: str) -> str:
    metadata = doc.metadata
    if table == "forecast_index":
        times = metadata["dates"]
        kind = "forecast"
    else:
        key = {"daily_index": "date", "live_index": "timestamp"}[table]
        times = [metadata[key]]
        kind = "observation"
    county = metadata.get("county")
    return (
        f"{metadata['station']} (station {metadata['id']})"
        + (f", {county} County" if county else "")
        + f": {', '.join(str(value) for value in times)} ({kind})"
    )
