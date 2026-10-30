"""Report chatbot usage to the AgWeatherNet backend, which stores it and serves the admin dashboard.

When AWN_BACKEND_URL and AWN_INTERNAL_KEY are set, every chat call (one question answered end to end, with
its chat and embedding model requests) is sent to the AgWeatherNet Go backend (awn_be_v2):

    POST {AWN_BACKEND_URL}/api/v1/internal/llm-usage/requests        one call
    POST {AWN_BACKEND_URL}/api/v1/internal/llm-usage/quality-runs    one retrieval quality check
    GET  {AWN_BACKEND_URL}/api/v1/internal/llm-usage/quality-runs/latest

authenticated with the X-Internal-Key header. The backend answers {"status": 1, "data": ...} on success and
{"status": 0, "error": ...} otherwise. The dashboard is the "LLM Usage" tab of the AgWeatherNet admin
dashboard, and the backend sends the monthly budget alert.

Calls are priced here (pricing.yaml or the cost the provider billed) and sent from a background thread
with retries, so a slow or unreachable backend never delays or fails a chat request. Re-sending a call is
harmless: the backend ignores a request_id it already has. No question or answer text is sent.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from backend.analytics.metering import RequestUsage
from backend.analytics.pricing import PriceTable

logger = logging.getLogger("awn.analytics")

_API_PREFIX = "/api/v1/internal/llm-usage"


class AwnBackendError(RuntimeError):
    """The AgWeatherNet backend rejected a report ({"status": 0}); sending it again will not help."""


class AwnUsageReporter:
    """Sends usage and retrieval quality runs to the AgWeatherNet backend."""

    def __init__(
        self,
        base_url: str,
        internal_key: str,
        prices: PriceTable | None = None,
        timeout: float = 5.0,
        retries: int = 3,
        max_queue: int = 1000,
    ) -> None:
        """Create a reporter and start its background sender thread."""
        self._base_url = base_url.rstrip("/")
        self._key = internal_key
        self._prices = prices or PriceTable.load()
        self._timeout = timeout
        self._retries = retries
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._send_loop, name="awn-usage-reporter", daemon=True)
        self._thread.start()

    @classmethod
    def from_env(cls) -> AwnUsageReporter | None:
        """Create a reporter from AWN_BACKEND_URL and AWN_INTERNAL_KEY, or None when either is unset."""
        base_url = (os.getenv("AWN_BACKEND_URL") or "").strip()
        key = (os.getenv("AWN_INTERNAL_KEY") or "").strip()
        if not base_url or not key:
            return None
        return cls(base_url, key)

    @property
    def base_url(self) -> str:
        """The AgWeatherNet backend usage is reported to."""
        return self._base_url

    def request_body(self, usage: RequestUsage, is_demo: bool = False) -> dict[str, Any]:
        """Build the JSON body for one call, pricing each model request."""
        model_calls = []
        for call in usage.calls:
            cost, priced = self._prices.call_cost(call)
            model_calls.append(
                {
                    "called_at": call.called_at.isoformat(),
                    "kind": call.kind,
                    "model": call.model,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "tokens_estimated": call.tokens_estimated,
                    "cost_usd": cost,
                    "priced": priced,
                    "cost_reported": call.cost_usd is not None,
                    "latency_ms": call.latency_ms,
                    "succeeded": call.succeeded,
                }
            )
        return {
            "request_id": str(usage.request_id),
            "user_id": usage.user_id,
            "session_id": usage.session_id,
            "started_at": usage.started_at.isoformat(),
            "latency_ms": usage.latency_ms,
            "status": usage.status,
            "error_type": usage.error_type,
            "is_demo": is_demo,
            "model_calls": model_calls,
        }

    def record(self, usage: RequestUsage) -> None:
        """Queue one call for sending; never blocks the chat request."""
        try:
            self._queue.put_nowait(self.request_body(usage))
        except queue.Full:
            logger.warning("Usage report queue is full, dropping request %s", usage.request_id)

    def record_quality_run(self, samples: int, passed: int, details: list[dict], is_demo: bool = False) -> None:
        """Send the result of one sampled retrieval quality check (raises if it could not be saved)."""
        body = {"samples": samples, "passed": passed, "details": details, "is_demo": is_demo}
        self._with_retries(lambda: self._request("POST", "/quality-runs", body))

    def latest_quality_run_at(self) -> datetime | None:
        """When the retrieval quality check last ran (demo runs excluded), or None if it never has."""
        data = self._with_retries(lambda: self._request("GET", "/quality-runs/latest"))
        run_at = (data or {}).get("run_at")
        return datetime.fromisoformat(run_at.replace("Z", "+00:00")) if run_at else None

    def close(self, timeout: float = 5.0) -> None:
        """Send what is still queued (for up to `timeout` seconds) and stop the sender thread."""
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout)

    def _send_loop(self) -> None:
        while True:
            body = self._queue.get()
            if body is None:
                return
            try:
                self._with_retries(lambda body=body: self._request("POST", "/requests", body))
            except Exception:
                logger.warning("Failed to report usage for request %s", body["request_id"], exc_info=True)

    def _with_retries(self, send: Any) -> Any:
        """Run `send`, retrying network and server errors with a short backoff; rejected reports are not retried."""
        for attempt in range(self._retries):
            try:
                return send()
            except AwnBackendError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == self._retries - 1:
                    raise
                time.sleep(0.5 * 2**attempt)
        return None

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self._base_url + _API_PREFIX + path,
            data=data,
            method=method,
            headers={"X-Internal-Key": self._key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode() or "{}")
        if payload.get("status") != 1:
            raise AwnBackendError(str(payload.get("error") or "the AgWeatherNet backend rejected the report"))
        return payload.get("data")
