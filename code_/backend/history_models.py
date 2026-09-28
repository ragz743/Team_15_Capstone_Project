"""Validated history intent and immutable evidence, separate from weather facts."""

from datetime import date
from typing import Literal

from backend.conversation_context import ConversationContext
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class HistoryIntent(BaseModel):
    """A model may select search criteria, never an owner or executable SQL."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["weather", "recall", "reuse", "clarify"]
    scope: Literal["all", "current", "previous"] = Field(
        default="all", description="all unless explicitly this chat (current) or the single last other chat (previous)"
    )
    terms: list[str] = Field(
        default_factory=list, max_length=8, description="Alternative topic keywords; [] for any topic"
    )
    start: date | None = Field(
        default=None, description="First inclusive local date the messages were SENT, if requested"
    )
    end: date | None = Field(default=None, description="Last inclusive sent date; same as start for a single day")
    clarification: str | None = Field(default=None, max_length=500)
    weather_question: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def coherent_intent(self):
        """Reject malformed dates, search terms and contradictory actions."""
        if any(not term.strip() or len(term) > 80 for term in self.terms):
            raise ValueError("History terms must contain 1–80 characters")
        if bool(self.start) != bool(self.end) or (self.start and self.end and self.start > self.end):
            raise ValueError("History dates must be an ordered inclusive pair")
        if self.end and self.end == date.max:
            raise ValueError("History date exceeds the supported calendar")
        if self.action == "clarify" and not (self.clarification and self.clarification.strip()):
            raise ValueError("An ambiguous request needs a clarification")
        if self.action == "reuse" and not (self.weather_question and self.weather_question.strip()):
            raise ValueError("Reusing history needs a new weather question")
        if self.action == "weather" and (self.terms or self.start or self.clarification or self.weather_question):
            raise ValueError("A weather route must not contain a history search")
        return self


class HistoryEntry(BaseModel):
    """A dated excerpt with a local reference; internal IDs never reach the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: int = Field(ge=1, le=20)
    title: str = Field(max_length=80)
    asked_at: AwareDatetime
    question: str = Field(max_length=1300)
    answer: str | None = Field(default=None, max_length=2500)
    context: ConversationContext | None = None


class HistorySnapshot(BaseModel):
    """Persist retrieved excerpts before answer generation, including a stable cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: HistoryIntent
    as_of: AwareDatetime
    entries: list[HistoryEntry] = Field(max_length=12)
    truncated: bool = False

    @model_validator(mode="after")
    def unique_references(self):
        """Only recall snapshots with unique evidence references can be answered."""
        if self.intent.action != "recall" or len({entry.ref for entry in self.entries}) != len(self.entries):
            raise ValueError("Invalid history evidence snapshot")
        return self
