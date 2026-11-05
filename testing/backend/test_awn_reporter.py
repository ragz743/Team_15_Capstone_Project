"""Unit tests for reporting usage to the AgWeatherNet backend (backend/analytics/awn_reporter.py)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import backend.api as api
import pytest
from backend.analytics.awn_reporter import AwnBackendError, AwnUsageReporter
from backend.analytics.metering import LlmCall, RequestUsage
from backend.analytics.usage_store import UsageTracker
from pytest import MonkeyPatch


class _FakeBackend:
    """A stand-in for the AgWeatherNet backend's internal llm-usage endpoints."""

    def __init__(self, key: str = "k3y", fail_first: int = 0, reject: bool = False) -> None:
        self.requests: list[tuple[str, str, dict | None, str | None]] = []
        self.fail_first = fail_first
        self.reject = reject
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # keep test output quiet
                pass

            def _reply(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                backend.requests.append((self.command, self.path, body, self.headers.get("X-Internal-Key")))
                if backend.fail_first > 0:
                    backend.fail_first -= 1
                    self.send_response(503)
                    self.end_headers()
                    return
                if self.headers.get("X-Internal-Key") != key:
                    payload = {"status": 0, "error": "unauthorized"}
                elif backend.reject:
                    payload = {"status": 0, "error": "status must be ok, empty, error, rate_limited, or unavailable"}
                else:
                    payload = {"status": 1, "data": {}}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _reply  # noqa: N815 - names BaseHTTPRequestHandler dispatches to

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def backend():
    """Run a fake AgWeatherNet backend that accepts the internal key "k3y"."""
    server = _FakeBackend()
    yield server
    server.close()


def _usage() -> RequestUsage:
    usage = RequestUsage(user_id="j.doe@wsu.edu", session_id="sess-1", latency_ms=1234, status="ok")
    at = datetime(2026, 10, 27, 17, 2, 10, tzinfo=UTC)
    usage.calls = [
        LlmCall("local/model", at, input_tokens=12, tokens_estimated=True),
        LlmCall("paid/model", at, input_tokens=1000, output_tokens=500, latency_ms=900, cost_usd=0.002),
        LlmCall("meta-llama/llama-3.3-70b-instruct:free", at, input_tokens=800, output_tokens=100, cost_usd=0.0),
        LlmCall("router/name", at, input_tokens=10, output_tokens=10, cost_usd=0.0042),
    ]
    return usage


def test_request_body_sends_the_reported_cost_of_every_model_request() -> None:
    """Each model request carries the cost OpenRouter reported, or $0 flagged as not reported."""
    reporter = AwnUsageReporter("http://unused", "k")
    body = reporter.request_body(_usage())
    reporter.close()

    assert (body["user_id"], body["session_id"], body["status"], body["latency_ms"]) == (
        "j.doe@wsu.edu",
        "sess-1",
        "ok",
        1234,
    )
    assert body["started_at"].endswith("+00:00")
    calls = body["model_calls"]
    assert [(c["kind"], c["cost_usd"], c["priced"], c["cost_reported"]) for c in calls] == [
        ("chat", 0.0, False, False),  # no cost reported
        ("chat", 0.002, True, True),
        ("chat", 0.0, True, True),  # :free, reported as $0
        ("chat", 0.0042, True, True),
    ]
    assert calls[0]["tokens_estimated"] is True
    json.dumps(body)  # serialisable as sent


def test_record_sends_the_call_in_the_background(backend: _FakeBackend) -> None:
    """record() returns at once; the call reaches the backend with the internal key."""
    reporter = AwnUsageReporter(backend.url, "k3y")
    usage = _usage()
    reporter.record(usage)
    reporter.close()

    method, path, body, key = backend.requests[0]
    assert (method, path, key) == ("POST", "/api/v1/internal/llm-usage/requests", "k3y")
    assert body is not None
    assert body["request_id"] == str(usage.request_id)
    assert len(body["model_calls"]) == 4


def test_server_errors_are_retried(monkeypatch: MonkeyPatch) -> None:
    """A temporarily unavailable backend gets the report on a later attempt."""
    monkeypatch.setattr("backend.analytics.awn_reporter.time.sleep", lambda _s: None)
    server = _FakeBackend(fail_first=2)
    try:
        reporter = AwnUsageReporter(server.url, "k3y")
        reporter.record(_usage())
        reporter.close()
        assert [r[1] for r in server.requests] == ["/api/v1/internal/llm-usage/requests"] * 3
    finally:
        server.close()


def test_rejected_reports_are_not_retried() -> None:
    """A {"status": 0} answer means the report itself is wrong, so sending it again will not help."""
    server = _FakeBackend(reject=True)
    try:
        reporter = AwnUsageReporter(server.url, "k3y")
        with pytest.raises(AwnBackendError):
            reporter._with_retries(lambda: reporter._request("POST", "/requests", reporter.request_body(_usage())))
        reporter.record(_usage())  # the sender thread logs the rejection instead of retrying
        reporter.close()
        assert len(server.requests) == 2
    finally:
        server.close()


def test_unreachable_backend_never_fails_the_chat_request() -> None:
    """Recording only queues; delivery failures are logged by the sender thread."""
    reporter = AwnUsageReporter("http://127.0.0.1:9", "k", timeout=0.2, retries=1)
    with UsageTracker(reporter).track("jdoe", None) as usage:
        usage.status = "ok"
    reporter.close()


def test_api_reports_to_agweathernet_when_configured(monkeypatch: MonkeyPatch) -> None:
    """With AWN_BACKEND_URL and AWN_INTERNAL_KEY set, usage goes to the backend instead of Postgres."""
    monkeypatch.setenv("AWN_BACKEND_URL", "http://awn.example")
    monkeypatch.setenv("AWN_INTERNAL_KEY", "k")
    store = api._build_usage_store()
    assert isinstance(store, AwnUsageReporter)
    store.close()

    monkeypatch.delenv("AWN_INTERNAL_KEY")
    assert AwnUsageReporter.from_env() is None


def test_chat_accepts_awn_usernames(monkeypatch: MonkeyPatch) -> None:
    """AWN usernames may contain . and @, so they are kept as the user id."""
    assert api._client_id("j.doe@wsu.edu") == "j.doe@wsu.edu"
    assert api._client_id("has spaces") is None
    assert api._client_id("x" * 65) is None
