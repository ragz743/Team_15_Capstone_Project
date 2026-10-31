"""Sampled retrieval quality: check the LangGraph chatbot finds the right weather data for known questions.

Running every user question through a quality check would double the model calls, so instead a fixed
sample of questions with known answers (retrieval_samples.yaml) is run through the weather workflow on a
schedule. A question passes when the workflow queried the expected kind of data (current, historical, or
forecast) at the expected station and got records back.
"""

from __future__ import annotations

import pathlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import yaml

_DEFAULT_SAMPLES_FILE = pathlib.Path(__file__).with_name("retrieval_samples.yaml")

# about three model requests per question; OpenRouter's free models allow 20 requests a minute
SCHEDULED_PAUSE_SECONDS = 10.0

Source = Literal["current", "historical", "forecast"]

# which workflow query node reads each kind of weather data
SOURCE_QUERY_TYPES: dict[str, str] = {
    "current": "current_weather",
    "historical": "historical_weather",
    "forecast": "forecast_weather",
}
_QUERY_TYPE_SOURCES = {query_type: source for source, query_type in SOURCE_QUERY_TYPES.items()}


class Execution(Protocol):
    """One database read made by the workflow (backend.workflow.contracts.QueryExecution)."""

    @property
    def query_type(self) -> str: ...  # noqa: D102

    @property
    def rows(self) -> Sequence[Any]: ...  # noqa: D102


# (question, station name) -> the workflow's database reads, e.g. LangGraphEngine.sample_executions
AskStation = Callable[[str, str], Sequence[Execution]]


@dataclass(frozen=True)
class Sample:
    """A question and the station and kind of weather data the workflow is expected to read for it."""

    question: str
    source: Source
    station: str


@dataclass
class QualityRun:
    """The outcome of evaluating every sample once."""

    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def samples(self) -> int:
        """Number of questions evaluated."""
        return len(self.details)

    @property
    def passed(self) -> int:
        """Number of questions whose expected weather data was found."""
        return sum(1 for detail in self.details if detail["passed"])

    @property
    def score(self) -> float | None:
        """Share of questions that passed, or None when nothing was evaluated."""
        return self.passed / self.samples if self.samples else None


def load_samples(path: str | pathlib.Path | None = None) -> list[Sample]:
    """Read the sample questions, defaulting to the bundled retrieval_samples.yaml."""
    with pathlib.Path(path or _DEFAULT_SAMPLES_FILE).open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    samples = [Sample(**entry) for entry in config.get("samples") or []]
    for sample in samples:
        if sample.source not in SOURCE_QUERY_TYPES:
            msg = f"unknown source {sample.source!r} for {sample.question!r}"
            raise ValueError(msg)
        if not sample.station.strip():
            msg = f"sample needs a station: {sample.question!r}"
            raise ValueError(msg)
    return samples


def evaluate(ask: AskStation, samples: list[Sample], pause_seconds: float = 0.0) -> QualityRun:
    """Check each sample: pass when the workflow read records of the expected kind at the expected station.

    `pause_seconds` spaces the questions out so the check does not hit the model provider's rate limit.
    """
    run = QualityRun()
    for i, sample in enumerate(samples):
        if i and pause_seconds > 0:
            time.sleep(pause_seconds)
        detail: dict[str, Any] = {
            "question": sample.question,
            "source": sample.source,
            "expected": sample.station,
            "passed": False,
            "found": [],
            "error": None,
        }
        try:
            executions = ask(sample.question, sample.station)
        except Exception as exc:  # one broken question should not stop the run
            detail["error"] = type(exc).__name__
            run.details.append(detail)
            continue

        # what the workflow read, for the dashboard table, e.g. "historical: 7 rows"
        detail["found"] = [_describe(execution) for execution in executions]
        detail["passed"] = any(
            execution.query_type == SOURCE_QUERY_TYPES[sample.source] and execution.rows for execution in executions
        )
        run.details.append(detail)
    return run


def run_and_record(
    ask: AskStation, store: Any, samples: list[Sample] | None = None, pause_seconds: float = 0.0
) -> QualityRun:
    """Evaluate the samples and save the run so the dashboard can show it."""
    run = evaluate(ask, samples if samples is not None else load_samples(), pause_seconds)
    store.record_quality_run(run.samples, run.passed, run.details)
    return run


def is_due(last_run_at: datetime | None, every_hours: float, now: datetime | None = None) -> bool:
    """Return True when the check has never run or last ran at least `every_hours` ago."""
    if last_run_at is None:
        return True
    now = now or datetime.now(UTC)
    return now - last_run_at >= timedelta(hours=every_hours)


def _describe(execution: Execution) -> str:
    source = _QUERY_TYPE_SOURCES.get(execution.query_type, execution.query_type)
    rows = len(execution.rows)
    return f"{source}: {rows} row{'' if rows == 1 else 's'}"
