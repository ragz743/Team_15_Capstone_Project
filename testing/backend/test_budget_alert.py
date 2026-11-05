"""Unit tests for the dashboard's scheduled check: the monthly budget alert."""

from __future__ import annotations

import ssl
from datetime import date
from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest
from backend.analytics.budget import BudgetConfig, BudgetMonitor, alert_message, send_with_smtp
from pytest import MonkeyPatch

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
    config = BudgetConfig(
        smtp_host="smtp.wsu.edu", smtp_sender="a@wsu.edu", dashboard_url="https://weather.wsu.edu/admin/"
    )
    body = alert_message(config, date(2026, 11, 1), 72.4).get_content()
    assert "November 2026" in body and "$72.40" in body and "https://weather.wsu.edu/admin/" in body


def test_budget_settings_are_optional() -> None:
    """With no email settings the API still starts; the alert is just not emailed."""
    assert not BudgetConfig().email_configured


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"smtp_host": "smtp.wsu.edu"}, "AWN_SMTP_FROM"),
        ({"smtp_sender": "a@wsu.edu"}, "AWN_SMTP_HOST"),
        ({"smtp_host": "smtp.wsu.edu", "smtp_sender": "a@wsu.edu", "smtp_username": "u"}, "AWN_SMTP_PASSWORD"),
        ({"threshold_usd": 0}, "AWN_MONTHLY_BUDGET_USD"),
        ({"smtp_port": 0}, "AWN_SMTP_PORT"),
    ],
)
def test_incomplete_budget_settings_fail_at_startup(settings: dict, problem: str) -> None:
    """A setup that could never send the alert is rejected when the API starts, not when the alert is due."""
    with pytest.raises(ValueError, match=problem):
        BudgetConfig(**settings)


def test_budget_settings_are_read_from_the_environment(monkeypatch: MonkeyPatch) -> None:
    """from_env applies the same checks to the AWN_* environment variables."""
    monkeypatch.setenv("AWN_SMTP_HOST", "smtp.wsu.edu")
    monkeypatch.delenv("AWN_SMTP_FROM", raising=False)
    with pytest.raises(ValueError, match="AWN_SMTP_FROM"):
        BudgetConfig.from_env()
    monkeypatch.setenv("AWN_SMTP_FROM", "awn-dashboard@wsu.edu")
    assert BudgetConfig.from_env().email_configured


def test_smtp_starttls_verifies_the_server_certificate(monkeypatch: MonkeyPatch) -> None:
    """STARTTLS uses a verifying context, so a fake server cannot capture the SMTP login."""
    smtp = MagicMock()
    monkeypatch.setattr("backend.analytics.budget.smtplib.SMTP", MagicMock(return_value=smtp))
    config = BudgetConfig(smtp_host="smtp.example", smtp_sender="a@b.c", smtp_username="u", smtp_password="p")
    send_with_smtp(config, EmailMessage())

    context = smtp.__enter__.return_value.starttls.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
