"""Coordinate map selection, interpretation and weather retrieval."""

from datetime import date

from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.models._chatbot_base import _BaseChatbot
from backend.station_catalog import StationCatalog
from backend.vector_store import PgVectorStore
from backend.weather_intent import WeatherIntent, WeatherInterpreter
from backend.weather_query import QueryClarificationError, RequestedPoint, Station
from backend.weather_records import TABLE_LABELS, append_sources, document_context, source_label
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
    """Share one catalog and one interpretation boundary across weather requests."""

    def __init__(
        self,
        vector_stores: PgVectorStore | list[PgVectorStore],
        chatbot: _BaseChatbot,
        *,
        catalog: StationCatalog | None = None,
        interpreter: WeatherInterpreter | None = None,
    ) -> None:
        """Keep source lookup reusable and model interpretation replaceable."""
        self._vector_stores = [vector_stores] if isinstance(vector_stores, PgVectorStore) else vector_stores
        self._chatbot = chatbot
        self._catalog = catalog or StationCatalog(
            lambda: [station for store in self._vector_stores for station in store.stations()]
        )
        self._interpreter = interpreter or WeatherInterpreter(chatbot)

    def retrieve(
        self, question: str, *, point: RequestedPoint | None = None, history: list[dict[str, str]] | None = None
    ) -> str:
        """Use the same validated flow for requests without saved conversations."""
        return self.answer_result(self.prepare_turn(question, point=point, history=history)).reply

    def prepare_turn(
        self,
        question: str,
        context: ConversationContext | None = None,
        *,
        point: RequestedPoint | None = None,
        history: list[dict[str, str]] | None = None,
        today: date | None = None,
    ) -> PreparedChatTurn:
        """Freeze model dates and the source chosen for the user's map point."""
        context = context or ConversationContext()
        point = point or context.point
        if point is None:
            return _clarification(question, context, "Choose a point on the map before asking about the weather.")
        if point != context.point:
            context = context.model_copy(update={"point": point, "station_ids": [], "county": None})
        try:
            station = self._catalog.resolve(point)
        except QueryClarificationError as exc:
            return _clarification(question, context, str(exc))
        intent = self._interpreter.interpret(question, point, station, context=context, history=history, today=today)
        if intent.action != "query":
            return _clarification(question, context, intent.message)
        if intent.location != "selected":
            return _clarification(
                question,
                context,
                "Your question refers to another or unclear location. Choose that point on the map, then ask again.",
            )
        return _weather_turn(intent, point, station)

    def answer_result(self, turn: PreparedChatTurn) -> AnsweredTurn:
        """Retrieve fresh evidence using frozen constraints, including on retries."""
        if turn.reply is not None:
            assert turn.outcome != "weather"
            return AnsweredTurn(reply=turn.reply, outcome=turn.outcome)
        sections, sources = self._collect_records(turn)
        if not sections:
            return AnsweredTurn(reply=NO_DATA, outcome="no_data")
        prompt = RAG_PROMPT_TEMPLATE.format(context="\n\n".join(sections), question=turn.question)
        answer = append_sources(self._chatbot.invoke([prompt]), sources)
        return AnsweredTurn(reply=answer, outcome="success")

    def _collect_records(self, turn: PreparedChatTurn) -> tuple[list[str], list[str]]:
        if turn.selection is None:
            raise ValueError("Weather retrieval requires a prepared selection")
        sections, sources = [], []
        for store in self._vector_stores:
            if not _uses_store(turn.context.data_kind, store.table):
                continue
            docs = store.similarity_search(turn.question, k=_SEARCH_K, selection=turn.selection)
            if docs:
                content = "\n\n".join(document_context(doc, store.table) for doc in docs)
                sections.append(f"[{TABLE_LABELS[store.table]}]\n{content}")
                sources.extend(source_label(doc, store.table) for doc in docs)
        return sections, sources


def _clarification(question: str, context: ConversationContext, reply: str) -> PreparedChatTurn:
    return PreparedChatTurn(outcome="needs_clarification", question=question, context=context, reply=reply)


def _weather_turn(intent: WeatherIntent, point: RequestedPoint, station: Station) -> PreparedChatTurn:
    selection = intent.selection(station)
    context = ConversationContext(
        point=point,
        station_ids=[station.id],
        start=selection.start,
        end=selection.end,
        subject=intent.subject,
        question=intent.question,
        data_kind=intent.data_kind,
    )
    return PreparedChatTurn(outcome="weather", question=intent.question, context=context, selection=selection)


def _uses_store(kind: str, table: str) -> bool:
    return kind == "both" or (table == "forecast_index") == (kind == "forecast")
