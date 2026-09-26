"""Validated weather context saved with each conversation."""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SUBJECTS = {
    "temperature": r"\b(?:temperature|temperatures|temp|hot|cold)\b",
    "humidity": r"\b(?:humidity|humid)\b",
    "precipitation": r"\b(?:precipitation|precip|rain|rainfall)\b",
    "wind": r"\bwind(?: speed| direction)?\b",
    "frost": r"\b(?:frost|freeze|freezing)\b",
    "soil temperature": r"\bsoil\b",
    "solar radiation": r"\b(?:solar|radiation)\b",
    "weather": r"\b(?:weather|conditions|forecast)\b",
}


class ConversationContext(BaseModel):
    """Validated partial intent belonging to one conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    station_ids: list[str] = Field(default_factory=list, max_length=1000)
    county: str | None = Field(default=None, max_length=100)
    start: date | None = None
    end: date | None = None
    subject: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_context(self):
        """Reject contradictory dates and unknown subject values at the boundary."""
        if bool(self.start) != bool(self.end) or (self.start and self.end and self.start > self.end):
            raise ValueError("Context needs a valid inclusive date range")
        if any(not re.fullmatch(r"\d{1,20}", value) for value in self.station_ids):
            raise ValueError("Invalid station ID")
        if self.subject and any(part not in _SUBJECTS for part in self.subject.split(", ")):
            raise ValueError("Unsupported weather subject")
        return self
