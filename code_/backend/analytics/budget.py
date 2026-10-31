"""Monthly LLM budget alert: email the AgWeatherNet team once a month's real spending passes the threshold."""

from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from email.message import EmailMessage

from backend.analytics.usage_store import UsageStore

logger = logging.getLogger("awn.budget")

_DEFAULT_THRESHOLD_USD = 50.0
_DEFAULT_RECIPIENTS = "weather@wsu.edu"


@dataclass(frozen=True)
class BudgetConfig:
    """Budget threshold, who to alert, and how to send email (all from environment variables)."""

    threshold_usd: float = _DEFAULT_THRESHOLD_USD
    recipients: str = _DEFAULT_RECIPIENTS  # comma separated
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_sender: str | None = None
    smtp_starttls: bool = True
    dashboard_url: str | None = None

    @classmethod
    def from_env(cls) -> BudgetConfig:
        """Read AWN_BUDGET_* and AWN_SMTP_* settings."""
        return cls(
            threshold_usd=float(os.getenv("AWN_MONTHLY_BUDGET_USD") or _DEFAULT_THRESHOLD_USD),
            recipients=os.getenv("AWN_BUDGET_ALERT_EMAIL") or _DEFAULT_RECIPIENTS,
            smtp_host=os.getenv("AWN_SMTP_HOST") or None,
            smtp_port=int(os.getenv("AWN_SMTP_PORT") or 587),
            smtp_username=os.getenv("AWN_SMTP_USERNAME") or None,
            smtp_password=os.getenv("AWN_SMTP_PASSWORD") or None,
            smtp_sender=os.getenv("AWN_SMTP_FROM") or None,
            smtp_starttls=(os.getenv("AWN_SMTP_STARTTLS") or "true").lower() != "false",
            dashboard_url=os.getenv("AWN_DASHBOARD_URL") or None,
        )

    @property
    def email_configured(self) -> bool:
        """True when there is enough SMTP configuration to send an email."""
        return bool(self.smtp_host and self.smtp_sender)


Sender = Callable[[BudgetConfig, EmailMessage], None]


def send_with_smtp(config: BudgetConfig, message: EmailMessage) -> None:
    """Send an email through the configured SMTP server."""
    assert config.smtp_host is not None
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
        if config.smtp_starttls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password or "")
        smtp.send_message(message)


def alert_message(config: BudgetConfig, month: date, spent_usd: float) -> EmailMessage:
    """Build the budget alert email."""
    message = EmailMessage()
    message["Subject"] = f"AgWeatherNet chatbot LLM spending passed ${config.threshold_usd:,.2f} for {month:%B %Y}"
    message["From"] = config.smtp_sender or ""
    message["To"] = config.recipients
    lines = [
        f"The AgWeatherNet weather assistant has spent ${spent_usd:,.2f} on LLM requests in {month:%B %Y},",
        f"which is over the monthly budget of ${config.threshold_usd:,.2f}.",
        "",
        "Per user costs and the models responsible are on the admin dashboard.",
    ]
    if config.dashboard_url:
        lines.append(config.dashboard_url)
    lines += ["", "This alert is sent once per month."]
    message.set_content("\n".join(lines))
    return message


class BudgetMonitor:
    """Checks month to date spending and sends one alert email per month once it passes the threshold."""

    def __init__(self, store: UsageStore, config: BudgetConfig, tz: str, send: Sender = send_with_smtp) -> None:
        """Create a monitor reading spending from `store`."""
        self._store = store
        self._config = config
        self._tz = tz
        self._send = send

    def check(self, now: datetime | None = None) -> None:
        """Send the alert if this month's spending is over budget and no alert has gone out yet."""
        month, spent = self._store.month_spend(self._tz, now)
        threshold = self._config.threshold_usd
        if spent < threshold:
            return
        if not self._store.claim_budget_alert(month, threshold, spent, self._config.recipients):
            return  # already sent this month, or another worker is handling it

        if not self._config.email_configured:
            logger.warning("LLM spending $%.2f passed the $%.2f budget but email is not configured", spent, threshold)
            self._store.finish_budget_alert(month, threshold, delivered=False, error="Email is not configured")
            return

        try:
            self._send(self._config, alert_message(self._config, month, spent))
        except Exception as exc:
            logger.exception("Failed to send the budget alert email")
            self._store.finish_budget_alert(month, threshold, delivered=False, error=f"{type(exc).__name__}: {exc}")
            return
        logger.info("Sent budget alert for %s to %s", month, self._config.recipients)
        self._store.finish_budget_alert(month, threshold, delivered=True, error=None)
