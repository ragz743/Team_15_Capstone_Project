"""Sampled retrieval quality: check the chatbot finds the right weather data for known questions.

Running every user question through a quality check would double the retrieval work, so instead a
fixed sample of questions with known answers (retrieval_samples.yaml) is evaluated on a schedule.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import yaml
from langchain_core.documents import Document

_DEFAULT_SAMPLES_FILE = pathlib.Path(__file__).with_name("retrieval_samples.yaml")

Source = Literal["current", "historical", "forecast"]

# which vector store table holds each kind of weather data
SOURCE_TABLES: dict[str, str] = {
    "current": "live_index",
    "historical": "daily_index",
    "forecast": "forecast_index",
}

# (question) -> [(table name, documents found)], e.g. Retriever.find_context
FindContext = Callable[[str], list[tuple[str, list[Document]]]]


@dataclass(frozen=True)
class Sample:
    """A question and the weather data the retriever is expected to find for it."""

    question: str
    source: Source
    station: str | None = None
    county: str | None = None

    def expected(self) -> tuple[str, str]:
        """Return (metadata key, value) the retrieved records must match."""
        if self.station:
            return "station", self.station
        if self.county:
            return "county", self.county
        msg = f"sample needs a station or county: {self.question!r}"
        raise ValueError(msg)


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
        """Number of questions whose expected weather data was retrieved."""
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
        if sample.source not in SOURCE_TABLES:
            msg = f"unknown source {sample.source!r} for {sample.question!r}"
            raise ValueError(msg)
        sample.expected()  # validates a station or county is given
    return samples


def evaluate(find_context: FindContext, samples: list[Sample]) -> QualityRun:
    """Check each sample: pass when the expected table returned a record for the expected station or county."""
    run = QualityRun()
    for sample in samples:
        key, value = sample.expected()
        table = SOURCE_TABLES[sample.source]
        detail: dict[str, Any] = {
            "question": sample.question,
            "source": sample.source,
            "expected": value,
            "passed": False,
            "found": [],
            "error": None,
        }
        try:
            docs = next((found for name, found in find_context(sample.question) if name == table), [])
        except Exception as exc:  # one broken question should not stop the run
            detail["error"] = type(exc).__name__
            run.details.append(detail)
            continue

        found = [str(doc.metadata.get(key, "")) for doc in docs]
        detail["found"] = list(dict.fromkeys(f for f in found if f))[:3]  # first few distinct matches, for the table
        detail["passed"] = any(f.lower() == value.lower() for f in found)
        run.details.append(detail)
    return run


def run_and_record(find_context: FindContext, store: Any, samples: list[Sample] | None = None) -> QualityRun:
    """Evaluate the samples and save the run so the dashboard can show it."""
    run = evaluate(find_context, samples if samples is not None else load_samples())
    store.record_quality_run(run.samples, run.passed, run.details)
    return run


def is_due(last_run_at: datetime | None, every_hours: float, now: datetime | None = None) -> bool:
    """Return True when the check has never run or last ran at least `every_hours` ago."""
    if last_run_at is None:
        return True
    now = now or datetime.now(UTC)
    return now - last_run_at >= timedelta(hours=every_hours)
