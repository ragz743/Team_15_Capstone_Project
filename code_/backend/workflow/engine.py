"""Adapt the weather graph to saved requests and the existing location picker."""

import re
from contextlib import closing
from datetime import datetime
from threading import RLock
from time import monotonic
from typing import Callable

from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.models._chatbot_base import _BaseChatbot
from backend.station_catalog import StationCatalog, StationList, browse_stations
from backend.weather_query import QueryClarificationError, RequestedPoint, Station
from backend.workflow.contracts import Source, WorkflowAnswer, WorkflowHistory, WorkflowRequest, WorkflowTimeoutError
from backend.workflow.workflow import ChatbotWorkflow, ClassifierChatbot


class AWNStationDirectory:
    """Cache active source identities independently of vector indexes."""

    def __init__(self, connection: Callable = AWNDatabaseConnection):
        """Keep source connections scoped to a catalog refresh."""
        self._connection = connection
        self._records: list[Station] = []
        self._expires = 0.0
        self._lock = RLock()

    def stations(self) -> list[Station]:
        """Load the station records used by the existing geographic catalog."""
        with self._lock:
            if monotonic() >= self._expires:
                with self._connection(statement_timeout=8) as db:
                    rows = list(
                        db.simple_query(
                            "SELECT UNIT_ID, STATION_NAME, COUNTY, STATION_LATDEG, STATION_LNGDEG, STATE "
                            "FROM METADATA WHERE ACTIVE_STATION = 'Y' AND UPPER(STATE) IN ('WA', 'WASHINGTON') "
                            "ORDER BY UNIT_ID LIMIT 1001",
                            (),
                        )
                    )
                if len(rows) > 1000:
                    raise ValueError("Station directory exceeds the supported size")
                self._records = [Station(*(str(value) if value is not None else "" for value in row)) for row in rows]
                self._expires = monotonic() + 300
            return list(self._records)


class LangGraphEngine:
    """Keep graph execution separate from HTTP, location selection and persistence."""

    def __init__(
        self,
        model: _BaseChatbot,
        classifier_model: _BaseChatbot,
        *,
        directory: AWNStationDirectory | None = None,
        workflow_factory: Callable = ChatbotWorkflow,
    ):
        """Share model clients while creating a fresh workflow for each answer."""
        self._model, self._classifier_model = model, classifier_model
        self._directory = directory or AWNStationDirectory()
        self._catalog = StationCatalog(self._directory.stations)
        self._workflow_factory = workflow_factory

    def station_catalog(self, point: RequestedPoint | None = None) -> StationList:
        """Reuse cached AWN metadata for browsing and optional nearby sorting."""
        return browse_stations(self._directory.stations(), point)

    def prepare_turn(
        self,
        question: str,
        context: ConversationContext | None = None,
        *,
        point: RequestedPoint | None = None,
        station_id: str | None = None,
        reference_time: datetime | None = None,
        history: list[dict] | None = None,
    ) -> PreparedChatTurn:
        """Freeze the station and dated context without interpreting the question."""
        context = context or ConversationContext()
        try:
            context = self._select_station(context, point, station_id)
        except QueryClarificationError as exc:
            return PreparedChatTurn(outcome="needs_clarification", question=question, context=context, reply=str(exc))
        request = WorkflowRequest(
            station_id=context.station_ids[0],
            reference_time=reference_time or datetime.now(TIMEZONE),
            history=[WorkflowHistory.model_validate(item) for item in (history or [])[-6:]],
        )
        return PreparedChatTurn(outcome="weather", question=question, context=context, workflow=request)

    def _select_station(
        self, context: ConversationContext, point: RequestedPoint | None, station_id: str | None
    ) -> ConversationContext:
        if station_id is not None:
            context = context.model_copy(update={"station_ids": [station_id], "county": None, "point": None})
        if point is not None and (point != context.point or not context.station_ids):
            station = self._catalog.resolve(point)
            return context.model_copy(update={"station_ids": [station.id], "county": None, "point": point})
        if len(context.station_ids) != 1:
            raise QueryClarificationError("Which station should I check? Choose a station from Browse stations.")
        if not any(station.id == context.station_ids[0] for station in self.station_catalog().stations):
            raise QueryClarificationError(
                "That station is no longer available. Choose another station from Browse stations."
            )
        return context

    def retrieve(
        self,
        question: str,
        *,
        point: RequestedPoint | None = None,
        station_id: str | None = None,
        history: list[dict] | None = None,
    ) -> str:
        """Support the unsaved chat endpoint through the same graph adapter."""
        recent = [{"user": item["content"]} for item in history or [] if item.get("role") == "user"]
        return self.answer_result(self.prepare_turn(question, point=point, station_id=station_id, history=recent)).reply

    def answer_result(self, turn: PreparedChatTurn) -> AnsweredTurn:
        """Run frozen inputs and distinguish missing observations from service failures."""
        if turn.reply is not None:
            assert turn.outcome != "weather"
            return AnsweredTurn(reply=turn.reply, outcome=turn.outcome)
        if turn.workflow is None:
            raise ValueError("This pending turn belongs to the previous weather engine. Send a new request.")
        station = next((item for item in self._directory.stations() if item.id == turn.workflow.station_id), None)
        if station is None:
            return AnsweredTurn(outcome="no_data", reply="The selected weather source is no longer available.")
        result = self._run_workflow(turn, station)
        self._validate_answer(result.reply)
        return self._answer_with_sources(result, station)

    def _run_workflow(self, turn: PreparedChatTurn, station: Station):
        request = turn.workflow
        assert request is not None
        with closing(
            self._workflow_factory(
                chat_model=self._model,
                classifier=ClassifierChatbot(self._classifier_model),
            )
        ) as workflow:
            try:
                return workflow.run_result(
                    turn.question,
                    station_id=int(station.id),
                    station_label=f"{station.name}, {station.county} County",
                    reference_time=request.reference_time,
                    history=[message.model_dump(mode="json") for message in request.history],
                )
            except TimeoutError as exc:
                raise WorkflowTimeoutError("Weather request exceeded its time limit") from exc

    @staticmethod
    def _validate_answer(reply: str) -> None:
        if not reply.strip():
            raise ValueError("The workflow returned an empty answer")
        if re.search(
            r"\b(?:latitude|longitude|station_lat|station_lng)\b|\b\d{1,2}\.\d{3,}\s*,\s*-\d{2,3}\.\d{3,}",
            reply,
            re.I,
        ):
            raise ValueError("The answer contains a restricted station location")

    @staticmethod
    def _answer_with_sources(result: WorkflowAnswer, station: Station) -> AnsweredTurn:
        sources = [
            Source(
                station_id=station.id,
                station=station.name,
                county=station.county,
                kind="forecast" if item.query_type == "forecast_weather" else "observation",
                times=item.times,
                measurements=item.measurements,
            )
            for item in result.executions
            if item.rows and item.times
        ]
        no_data = bool(result.executions) and not any(item.rows for item in result.executions)
        reply = result.reply
        if result.executions:
            reply += f"\n\nSource station: {station.name}, {station.county} County."
        return AnsweredTurn(
            reply=reply,
            outcome="no_data" if no_data else "success",
            sources=sources,
            coverage="subset" if result.executions else None,
        )
