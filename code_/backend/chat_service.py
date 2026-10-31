"""Saved conversation orchestration independent of HTTP and cookie handling."""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import psycopg
from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.conversation_store import AcceptedTurn, ConversationNotFoundError, ConversationStore, TurnConflictError
from backend.history_service import HistoryResolution, HistoryService
from backend.retriever import Retriever
from backend.weather_query import RequestedPoint

logger = logging.getLogger(__name__)


class ChatServiceError(Exception):
    """A provider failure with the operation needed for a useful client response."""

    def __init__(self, operation: str, reason: str = "failed"):
        """Keep provider details in the exception cause, outside public messages."""
        super().__init__(operation, reason)
        self.operation = operation
        self.reason = reason


@contextmanager
def _operation(name: str):
    try:
        yield
    except (ChatServiceError, ConversationNotFoundError, TurnConflictError):
        raise
    except Exception as exc:
        raise ChatServiceError(name) from exc


@dataclass(frozen=True)
class ChatCompletion:
    """One answer and the context committed alongside it."""

    answer: AnsweredTurn
    model: str
    context: ConversationContext

    def response(self) -> dict:
        """Project the saved result without exposing internal attempts or evidence."""
        return {**self.answer.model_dump(), "model": self.model, "context": self.context}


class SavedChatService:
    """Accept, prepare, answer and persist each turn with short transactions."""

    def __init__(
        self, store: ConversationStore, history: HistoryService | None, weather: Retriever | None, model_name: str
    ):
        """Use the application services without opening connections or invoking models."""
        self.store, self.history, self.weather, self.model_name = store, history, weather, model_name

    def run(
        self, owner: UUID, conversation: UUID, request: UUID, question: str, *, point: RequestedPoint | None = None
    ) -> ChatCompletion:
        """Replay completed results and freeze new inputs before answer generation."""
        request_input = {"point": point.model_dump()} if point is not None else {}
        turn = self.store.begin(owner, conversation, request, question, request_input=request_input)
        if turn.completed is not None:
            return self._replay(turn)
        try:
            prepared = turn.prepared
            if prepared is None:
                prepared = self._prepare(owner, conversation, question, turn, point)
                self.store.prepare(owner, conversation, request, turn.attempt_id, prepared)
            result = self._answer(prepared)
            self.store.complete(
                owner,
                conversation,
                request,
                turn.attempt_id,
                result.answer.reply,
                result.model,
                result.context,
                metadata=result.answer.model_dump(mode="json", exclude={"reply"}),
            )
            return result
        except Exception:
            self._record_failure(owner, conversation, request, turn.attempt_id)
            raise

    def _replay(self, turn: AcceptedTurn) -> ChatCompletion:
        assert turn.completed is not None
        result = turn.completed
        return ChatCompletion(
            AnsweredTurn(reply=result["reply"], outcome=result.get("outcome", "success")), result["model"], turn.context
        )

    def _prepare(
        self, owner: UUID, conversation: UUID, question: str, turn: AcceptedTurn, point: RequestedPoint | None
    ) -> PreparedChatTurn:
        with _operation("history"):
            if self.history is None:
                raise ChatServiceError("history", "unavailable")
            resolution = self.history.prepare(self.store, owner, conversation, question, accepted_at=turn.requested_at)
        if resolution.snapshot is not None:
            return PreparedChatTurn(
                outcome="history", question=question, context=turn.context, history=resolution.snapshot
            )
        if resolution.reply is not None:
            return PreparedChatTurn(
                outcome="needs_clarification" if resolution.intent.action == "clarify" else "history",
                question=question,
                context=turn.context,
                reply=resolution.reply,
            )
        return self._prepare_weather(question, turn, resolution, point)

    def _prepare_weather(
        self, question: str, turn: AcceptedTurn, resolution: HistoryResolution, point: RequestedPoint | None
    ) -> PreparedChatTurn:
        """Resolve weather inputs using the accepted time and selected context."""
        context = turn.context
        if resolution.intent.action == "reuse":
            question = resolution.intent.weather_question or question
            context = resolution.context or context
        with _operation("weather"):
            if self.weather is None:
                raise ChatServiceError("weather", "unavailable")
            return self.weather.prepare_turn(
                question,
                context,
                point=point,
                today=turn.requested_at.astimezone(TIMEZONE).date(),
                history=resolution.recent if resolution.intent.action == "weather" else [],
            )

    def _answer(self, prepared: PreparedChatTurn) -> ChatCompletion:
        operation = "history" if prepared.history is not None or prepared.outcome == "history" else "weather"
        with _operation(operation):
            if prepared.reply is not None:
                assert prepared.outcome != "weather"
                answer = AnsweredTurn(reply=prepared.reply, outcome=prepared.outcome)
                model = "saved-history" if operation == "history" else self.model_name
            elif prepared.history is not None:
                if self.history is None:
                    raise ChatServiceError("history", "unavailable")
                answer = AnsweredTurn(reply=self.history.answer(prepared.question, prepared.history), outcome="history")
                model = self.history.model_name
            else:
                if self.weather is None:
                    raise ChatServiceError("weather", "unavailable")
                answer, model = self.weather.answer_result(prepared), self.model_name
            if not answer.reply.strip():
                raise ChatServiceError(operation, "empty")
        return ChatCompletion(answer, model, prepared.context)

    def _record_failure(self, owner: UUID, conversation: UUID, request: UUID, attempt: UUID) -> None:
        try:
            self.store.fail(owner, conversation, request, attempt)
        except psycopg.Error:
            logger.error("Could not record failed conversation turn")
