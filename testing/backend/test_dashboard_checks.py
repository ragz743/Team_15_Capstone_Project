"""Unit tests for the dashboard's scheduled checks: sampled retrieval quality and the monthly budget alert."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.analytics import retrieval_quality
from backend.analytics.budget import BudgetConfig, BudgetMonitor, alert_message
from backend.analytics.retrieval_quality import Sample, evaluate, is_due, load_samples
from langchain_core.documents import Document
from pytest import MonkeyPatch

# ---------- retrieval quality ----------


def _doc(station: str, county: str = "Whitman") -> Document:
    return Document(page_content="", metadata={"station": station, "county": county})


def test_bundled_sample_questions_are_valid() -> None:
    """The shipped sample file parses and every question names what it expects to find."""
    samples = load_samples()
    assert len(samples) >= 10
    assert {sample.source for sample in samples} == {"current", "historical", "forecast"}


def test_evaluate_passes_only_when_the_expected_data_is_in_the_right_table() -> None:
    """A question passes when the expected table returned a record for the expected station or county."""
    results = {
        "Pullman now?": [("live_index", [_doc("Pullman")]), ("daily_index", [])],
        "Fairfield yesterday?": [("live_index", [_doc("Fairfield")]), ("daily_index", [_doc("Pullman")])],
        "Douglas County this week?": [("daily_index", [_doc("Mansfield", "Douglas")])],
    }
    samples = [
        Sample("Pullman now?", "current", station="pullman"),  # case insensitive
        Sample("Fairfield yesterday?", "historical", station="Fairfield"),  # right station, wrong table
        Sample("Douglas County this week?", "historical", county="Douglas"),
    ]

    run = evaluate(lambda question: results[question], samples)

    assert [d["passed"] for d in run.details] == [True, False, True]
    assert (run.samples, run.passed, run.score) == (3, 2, pytest.approx(2 / 3))
    assert run.details[1]["found"] == ["Pullman"]


def test_evaluate_records_errors_without_stopping() -> None:
    """A failing question counts as missed and the rest still run."""

    def find(question: str):
        if question == "boom":
            raise TimeoutError
        return [("live_index", [_doc("Pullman")])]

    run = evaluate(find, [Sample("boom", "current", station="Pullman"), Sample("ok", "current", station="Pullman")])

    assert [(d["passed"], d["error"]) for d in run.details] == [(False, "TimeoutError"), (True, None)]


def test_quality_check_is_due_daily() -> None:
    """The check runs when it never ran or the last run is at least a day old."""
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    assert is_due(None, 24, now)
    assert is_due(now - timedelta(hours=25), 24, now)
    assert not is_due(now - timedelta(hours=2), 24, now)


def test_api_runs_the_quality_check_only_when_due(monkeypatch: MonkeyPatch) -> None:
    """The hourly loop records a run when the last one is old, and skips it otherwise."""
    retriever = MagicMock()
    retriever.find_context.return_value = [("live_index", [_doc("Pullman")])]
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(retrieval_quality, "load_samples", lambda: [Sample("q", "current", station="Pullman")])
    store = MagicMock()

    store.latest_quality_run_at.return_value = datetime.now(UTC) - timedelta(hours=1)
    api._check_quality_if_due(store)
    store.record_quality_run.assert_not_called()

    store.latest_quality_run_at.return_value = None
    api._check_quality_if_due(store)
    store.record_quality_run.assert_called_once()
    samples, passed, details = store.record_quality_run.call_args.args
    assert (samples, passed, details[0]["question"]) == (1, 1, "q")


# ---------- monthly budget alert ----------

_SMTP = BudgetConfig(threshold_usd=50.0, smtp_host="smtp.wsu.edu", smtp_sender="awn-dashboard@wsu.edu")


def _monitor(spent: float, claimed: bool = True, config: BudgetConfig = _SMTP):
    store = MagicMock()
    store.month_spend.return_value = (date(2026, 10, 1), spent)
    store.claim_budget_alert.return_value = claimed
    sent: list[EmailMessage] = []
    return BudgetMonitor(store, config, "America/Los_Angeles", send=lambda _c, msg: sent.append(msg)), store, sent


def test_budget_defaults_follow_the_client() -> None:
    """$50 a month, alerts to weather@wsu.edu."""
    config = BudgetConfig.from_env()
    assert (config.threshold_usd, config.recipients) == (50.0, "weather@wsu.edu")


def test_no_alert_under_budget() -> None:
    """Spending under the threshold sends nothing and claims nothing."""
    monitor, store, sent = _monitor(49.99)
    monitor.check()
    store.claim_budget_alert.assert_not_called()
    assert sent == []


def test_alert_is_emailed_once_spending_passes_the_budget() -> None:
    """Over budget: the alert is claimed, emailed to weather@wsu.edu, and marked delivered."""
    monitor, store, sent = _monitor(50.5)
    monitor.check()

    [message] = sent
    assert message["To"] == "weather@wsu.edu"
    assert "$50.00" in message["Subject"] and "October 2026" in message["Subject"]
    assert "$50.50" in message.get_content()
    store.finish_budget_alert.assert_called_once_with(date(2026, 10, 1), 50.0, delivered=True, error=None)


def test_no_second_email_when_already_claimed() -> None:
    """When this month's alert was already sent (claim refused), nothing is sent again."""
    monitor, store, sent = _monitor(80.0, claimed=False)
    monitor.check()
    assert sent == []
    store.finish_budget_alert.assert_not_called()


def test_send_failures_are_recorded_for_retry() -> None:
    """An SMTP error is saved on the alert so the dashboard shows it and the next hour retries."""
    monitor, store, _ = _monitor(60.0)

    def fail(_config, _message):
        raise ConnectionRefusedError("smtp.wsu.edu refused")

    monitor._send = fail
    monitor.check()

    _, kwargs = store.finish_budget_alert.call_args
    assert kwargs["delivered"] is False and "ConnectionRefusedError" in kwargs["error"]


def test_unconfigured_email_is_reported_not_sent() -> None:
    """Without SMTP settings the alert is recorded as undelivered with a clear reason."""
    monitor, store, sent = _monitor(60.0, config=BudgetConfig())
    monitor.check()
    assert sent == []
    _, kwargs = store.finish_budget_alert.call_args
    assert (kwargs["delivered"], kwargs["error"]) == (False, "Email is not configured")


def test_alert_message_links_to_the_dashboard() -> None:
    """The email names the month, the spend, the budget, and the dashboard link when configured."""
    config = BudgetConfig(smtp_sender="a@wsu.edu", dashboard_url="https://weather.wsu.edu/admin/")
    body = alert_message(config, date(2026, 11, 1), 72.4).get_content()
    assert "November 2026" in body and "$72.40" in body and "https://weather.wsu.edu/admin/" in body


# ---------- vector store connection recovery ----------


def test_failed_vector_store_query_does_not_poison_the_connection() -> None:
    """A failed query rolls back so later chat and quality-check queries on the same connection still work."""
    from threading import Lock

    import psycopg
    from backend.databases.pgvector import PgVectorConnection

    connection = object.__new__(PgVectorConnection)
    connection.conn = MagicMock()
    connection._query_lock = Lock()
    cursor = connection.conn.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = psycopg.errors.UndefinedTable("no such table")

    with pytest.raises(psycopg.errors.UndefinedTable):
        list(connection.simple_query(b"SELECT 1", ()))
    transaction = connection.conn.transaction.return_value
    assert transaction.__exit__.call_args.args[0] is psycopg.errors.UndefinedTable
