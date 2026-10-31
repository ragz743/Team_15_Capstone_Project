"""Inputs retained for retries and results returned by the weather graph."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WorkflowClassificationError(ValueError):
    """The classifier could not produce a valid query plan."""


class WorkflowTimeoutError(TimeoutError):
    """A weather workflow exceeded its request budget."""


class WorkflowHistory(BaseModel):
    """A bounded previous turn used only to interpret the current question."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    user: str = Field(max_length=1200)
    assistant: str = Field(default="", max_length=2000)
    asked_at: str | None = None


class WorkflowRequest(BaseModel):
    """Freeze the selected station and reference time before running the graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    station_id: str = Field(pattern=r"^\d{1,20}$")
    reference_time: AwareDatetime
    history: list[WorkflowHistory] = Field(default_factory=list, max_length=6)


@dataclass(frozen=True)
class QueryExecution:
    """Keep executed records separate from previous conversation answers."""

    query_type: str
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    times: list[str]
    measurements: list[str]


@dataclass(frozen=True)
class WorkflowAnswer:
    """Return the answer together with its database evidence."""

    reply: str
    executions: list[QueryExecution]


class Source(BaseModel):
    """Weather provenance without source coordinates or raw records."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    station_id: str = Field(pattern=r"^\d{1,20}$")
    station: str = Field(min_length=1, max_length=200)
    county: str | None = None
    kind: Literal["observation", "forecast"]
    times: list[str] = Field(min_length=1, max_length=1000)
    measurements: list[str] = Field(default_factory=list)
