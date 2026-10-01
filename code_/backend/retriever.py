"""Code for the data retriever controller class, Retriever."""

from backend.models._chatbot_base import _BaseChatbot
from backend.station_catalog import StationCatalog
from backend.vector_store import PgVectorStore
from backend.weather_intent import WeatherIntent, WeatherInterpreter
from backend.weather_query import QueryClarificationError, RequestedPoint, WeatherQuery
from backend.weather_records import (
    TABLE_LABELS,
    append_sources,
    document_context,
    source_label,
)
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
        - The source was selected for the user chosen map point. Explain that
          measurements come from the nearby source, not necessarily the exact point.
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
        - If the question is ambiguous — unclear location, unclear time
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


class Retriever:
    """Coordinate location lookup, interpretation, retrieval and grounded answers."""

    def __init__(
        self,
        vector_stores: PgVectorStore | list[PgVectorStore],
        chatbot: _BaseChatbot,
        *,
        catalog: StationCatalog | None = None,
        interpreter: WeatherInterpreter | None = None,
    ) -> None:
        """Create the reusable catalog and interpretation boundary."""
        self._vector_stores = [vector_stores] if isinstance(vector_stores, PgVectorStore) else vector_stores
        if not self._vector_stores:
            raise ValueError("At least one weather index is required")
        self._chatbot = chatbot
        self._catalog = catalog or self._vector_stores[0].station_catalog(
            tuple(store.table for store in self._vector_stores)
        )
        self._interpreter = interpreter or WeatherInterpreter(chatbot)

    def retrieve(
        self,
        question: str,
        *,
        point: RequestedPoint | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Resolve a map point and validate the model interpretation before searching."""
        if point is None:
            return "Choose a point on the map before asking about the weather."
        try:
            station = self._catalog.resolve(point)
        except QueryClarificationError as exc:
            return str(exc)
        intent = self._interpreter.interpret(question, point, station, history=history)
        if intent.action != "query":
            return intent.message
        if intent.location != "selected":
            return "Your question refers to another or unclear location. Choose that point on the map, then ask again."
        selection = intent.selection(station)
        sections, sources = self._collect_records(intent, selection)
        if not sections:
            return NO_DATA
        prompt = RAG_PROMPT_TEMPLATE.format(context="\n\n".join(sections), question=intent.question)
        return append_sources(self._chatbot.invoke([prompt]), sources)

    def _collect_records(self, intent: WeatherIntent, selection: WeatherQuery) -> tuple[list[str], list[str]]:
        sections, sources = [], []
        for store in self._vector_stores:
            if not _uses_store(intent, store.table):
                continue
            docs = store.similarity_search(intent.question, k=_SEARCH_K, selection=selection)
            if docs:
                content = "\n\n".join(document_context(doc, store.table) for doc in docs)
                sections.append(f"[{TABLE_LABELS[store.table]}]\n{content}")
                sources.extend(source_label(doc, store.table) for doc in docs)
        return sections, sources


def _uses_store(intent: WeatherIntent, table: str) -> bool:
    if intent.data_kind == "both":
        return True
    return (table == "forecast_index") == (intent.data_kind == "forecast")
