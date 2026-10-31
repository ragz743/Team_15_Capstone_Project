"""Validated weather context persisted with each conversation."""

import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from backend.weather_query import RequestedPoint
from pydantic import BaseModel, ConfigDict, Field, model_validator

TIMEZONE = ZoneInfo("America/Los_Angeles")


class ConversationContext(BaseModel):
    """Keep accepted constraints without interpreting language or choosing sources."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    station_ids: list[str] = Field(default_factory=list, max_length=1000)
    county: str | None = Field(default=None, max_length=100)
    start: date | None = None
    end: date | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    point: RequestedPoint | None = None
    data_kind: Literal["observation", "forecast", "both"] = "both"
    question: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def valid_context(self):
        """Validate persisted data while accepting contexts saved before map selection."""
        if bool(self.start) != bool(self.end) or (self.start and self.end and self.start > self.end):
            raise ValueError("Context needs a valid inclusive date range")
        if any(not re.fullmatch(r"\d{1,20}", value) for value in self.station_ids):
            raise ValueError("Invalid station ID")
        if self.subject is not None and not self.subject.strip():
            raise ValueError("A weather subject cannot be blank")
        return self
