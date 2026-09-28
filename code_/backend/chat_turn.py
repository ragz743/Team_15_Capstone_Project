"""Durable resolved inputs for one accepted conversation request."""

from typing import Literal

from backend.conversation_context import ConversationContext
from backend.history_models import HistorySnapshot
from backend.weather_query import WeatherQuery
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnsweredTurn(BaseModel):
    """The answer and public provenance saved together for exact replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reply: str
    outcome: Literal["success", "history", "needs_clarification", "no_data"]


class PreparedChatTurn(BaseModel):
    """Freeze resolution before retrieval so a retry cannot change its meaning."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: Literal["weather", "history", "needs_clarification", "no_data"]
    question: str = Field(min_length=1)
    context: ConversationContext
    selection: WeatherQuery | None = None
    reply: str | None = None
    history: HistorySnapshot | None = None

    @model_validator(mode="after")
    def consistent_selection(self):
        """Keep executable constraints identical to the persisted context."""
        if self.history is not None:
            if self.outcome != "history" or self.selection is not None or self.reply is not None:
                raise ValueError("History evidence cannot coexist with weather execution or a prepared reply")
        if self.outcome == "weather":
            query = self.selection
            if query is None or not query.station_ids or query.start > query.end:
                raise ValueError("A weather turn needs a resolved station and period")
            if (
                list(query.station_ids) != self.context.station_ids
                or query.start != self.context.start
                or query.end != self.context.end
                or query.county != self.context.county
                or not self.context.subject
                or self.reply is not None
            ):
                raise ValueError("Weather constraints must match the saved context")
        elif self.history is None and (self.selection is not None or not self.reply or not self.reply.strip()):
            raise ValueError("A completed resolution needs a nonblank reply and no executable query")
        return self
