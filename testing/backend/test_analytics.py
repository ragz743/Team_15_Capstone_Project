"""Unit tests for usage metering, pricing, request tracking, and the admin metrics endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import backend.api as api
import pytest
from backend.analytics import admin_api
from backend.analytics.metering import LlmCall, MeteredEmbedding, RequestUsage, metered
from backend.analytics.pricing import ModelPrice, PriceTable
from backend.analytics.usage_store import (
    UsageStore,
    UsageStoreUnavailableError,
    UsageTracker,
)
from backend.models._embedding_base import _BaseEmbedding
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from psycopg import OperationalError
from pytest import MonkeyPatch


def _fake_chat(message: AIMessage) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([message]))


class _FakeEmbedding(_BaseEmbedding):
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        return [0.0], document

    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        return [([0.0], d) for d in documents]


# ---------- pricing ----------


def test_price_table_costs_listed_models_per_million_tokens() -> None:
    """Listed models are priced from their input and output rates."""
    prices = PriceTable({"paid/model": ModelPrice(2.0, 8.0)})
    cost, priced = prices.cost("paid/model", input_tokens=1_000, output_tokens=500)
    assert priced
    assert cost == pytest.approx((1_000 * 2.0 + 500 * 8.0) / 1_000_000)


def test_price_table_free_suffix_and_unknown_models() -> None:
    """Free tier models cost nothing; unknown models cost nothing but are flagged unpriced."""
    prices = PriceTable({}, free_suffixes=(":free",))
    assert prices.cost("openai/gpt-oss-20b:free", 10_000, 10_000) == (0.0, True)
    assert prices.cost("someone/new-model", 10_000, 10_000) == (0.0, False)


def test_bundled_pricing_file_loads() -> None:
    """The bundled pricing.yaml parses and treats free tier models as priced."""
    prices = PriceTable.load()
    assert prices.cost("any/model:free", 1, 1) == (0.0, True)


# ---------- metering ----------


def test_metered_records_reported_chat_tokens() -> None:
    """Provider reported token usage and model name are recorded for chat calls."""
    usage = RequestUsage()
    model = _fake_chat(
        AIMessage(
            content="72°F in Pullman",
            usage_metadata={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128},
            response_metadata={"model_name": "openai/gpt-oss-20b:free"},
        )
    )
    with metered(usage):
        model.invoke(["What is the temperature in Pullman?"])

    [call] = usage.calls
    assert (call.kind, call.model, call.input_tokens, call.output_tokens) == ("chat", "openai/gpt-oss-20b:free", 120, 8)
    assert call.requested_model == "unknown"  # the fake model reports no requested name
    assert not call.tokens_estimated
    assert call.succeeded


def test_metered_estimates_tokens_when_not_reported() -> None:
    """Calls without usage metadata fall back to a character based estimate."""
    usage = RequestUsage()
    with metered(usage):
        _fake_chat(AIMessage(content="12345678")).invoke(["1234"])

    [call] = usage.calls
    assert call.tokens_estimated
    assert (call.input_tokens, call.output_tokens) == (1, 2)


def test_calls_outside_metered_block_are_not_recorded() -> None:
    """Model calls made outside a request are ignored."""
    usage = RequestUsage()
    with metered(usage):
        pass
    _fake_chat(AIMessage(content="hi")).invoke(["hi"])
    assert usage.calls == []


def test_metered_embedding_records_each_call() -> None:
    """Embedding calls are recorded with estimated tokens and the configured model name."""
    usage = RequestUsage()
    embedding = MeteredEmbedding(_FakeEmbedding(), "openai/text-embedding-3-small")
    with metered(usage):
        embedding.embed_document(Document(page_content="x" * 40))
        embedding.embed_documents([Document(page_content="abcd"), Document(page_content="efgh")])

    assert [(c.kind, c.model, c.input_tokens, c.tokens_estimated) for c in usage.calls] == [
        ("embedding", "openai/text-embedding-3-small", 10, True),
        ("embedding", "openai/text-embedding-3-small", 2, True),
    ]


def test_metered_embedding_records_failed_calls() -> None:
    """A failing embedding call is still recorded, marked unsuccessful, and the error propagates."""
    inner = MagicMock(spec=_BaseEmbedding)
    inner.embed_document.side_effect = RuntimeError("provider down")
    usage = RequestUsage()
    with metered(usage), pytest.raises(RuntimeError):
        MeteredEmbedding(inner, "m").embed_document(Document(page_content="q"))

    [call] = usage.calls
    assert not call.succeeded


# ---------- usage store (no database) ----------


def test_store_prices_routed_models_by_the_requested_model() -> None:
    """A router answering under an unlisted model name is priced by the configured model instead."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    store = UsageStore(lambda: conn, PriceTable({"openrouter/free": ModelPrice(0, 0)}))
    usage = RequestUsage(status="ok")
    usage.calls = [
        LlmCall(
            kind="chat", model="vendor/picked-model", requested_model="openrouter/free", called_at=usage.started_at
        ),
        LlmCall(kind="chat", model="vendor/unknown", requested_model="vendor/unknown", called_at=usage.started_at),
    ]
    store.record(usage)

    [rows] = [c.args[1] for c in cursor.executemany.call_args_list]
    priced = [row[8] for row in rows]  # the priced column
    assert priced == [True, False]


def test_store_backs_off_after_the_database_is_unreachable() -> None:
    """After a failed connect, writes are skipped quickly instead of every request waiting on the database."""
    connect = MagicMock(side_effect=OperationalError("connection refused"))
    store = UsageStore(connect, PriceTable({}))

    with pytest.raises(OperationalError):
        store.record(RequestUsage(status="ok"))
    attempts = connect.call_count

    with pytest.raises(UsageStoreUnavailableError):
        store.record(RequestUsage(status="ok"))
    assert connect.call_count == attempts  # no new connection attempt during the back-off

    # the tracker treats the back-off as a skipped write, not a failure of the chat request
    with UsageTracker(store).track(None, None) as usage:
        usage.status = "ok"


# ---------- request tracking ----------


def test_tracker_records_status_latency_and_calls() -> None:
    """A tracked request is recorded once with its status and calls."""
    store = MagicMock()
    with UsageTracker(store).track("user-1", "session-1") as usage:
        usage.calls.append(LlmCall(kind="chat", model="m", called_at=usage.started_at))
        usage.status = "ok"

    [recorded] = [c.args[0] for c in store.record.call_args_list]
    assert (recorded.user_id, recorded.session_id, recorded.status) == ("user-1", "session-1", "ok")
    assert recorded.latency_ms >= 0
    assert len(recorded.calls) == 1


def test_tracker_marks_unhandled_exceptions_as_errors() -> None:
    """An exception without an explicit status is recorded as an error with its type name."""
    store = MagicMock()
    with pytest.raises(ValueError), UsageTracker(store).track(None, None):
        raise ValueError("boom")

    recorded = store.record.call_args.args[0]
    assert (recorded.status, recorded.error_type) == ("error", "ValueError")


def test_tracker_skips_requests_marked_not_to_record() -> None:
    """Requests flagged record=False, such as invalid input, are not stored."""
    store = MagicMock()
    with UsageTracker(store).track(None, None) as usage:
        usage.record = False
    store.record.assert_not_called()


def test_tracker_never_fails_the_request_when_recording_fails() -> None:
    """A database failure while recording is logged, not raised."""
    store = MagicMock()
    store.record.side_effect = RuntimeError("database down")
    with UsageTracker(store).track(None, None) as usage:
        usage.status = "ok"


# ---------- /api/chat integration ----------


class _Retriever:
    def __init__(self, reply: str = "answer", error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error

    def retrieve(self, question: str, filter: dict | None = None) -> str:
        if self._error is not None:
            raise self._error
        return self._reply


def _post_chat(headers: dict[str, str] | None = None, content: str = "Weather in Pullman?"):
    return TestClient(api.app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": content}]}, headers=headers or {}
    )


@pytest.fixture
def recorded(monkeypatch: MonkeyPatch) -> MagicMock:
    """Replace the API's usage tracker with one writing to a mock store."""
    store = MagicMock()
    monkeypatch.setattr(api, "_usage_tracker", UsageTracker(store))
    return store


def test_chat_records_user_and_session_headers(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Valid client ids from headers are recorded with a successful request."""
    monkeypatch.setattr(api, "_retriever", _Retriever())
    response = _post_chat({"X-AWN-User-Id": "browser-123", "X-AWN-Session-Id": "conv_9"})

    assert response.status_code == 200
    usage = recorded.record.call_args.args[0]
    assert (usage.user_id, usage.session_id, usage.status) == ("browser-123", "conv_9", "ok")


def test_chat_ignores_malformed_client_ids(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Header values outside the allowed id format are dropped rather than stored."""
    monkeypatch.setattr(api, "_retriever", _Retriever())
    _post_chat({"X-AWN-User-Id": "x" * 65, "X-AWN-Session-Id": "has spaces"})

    usage = recorded.record.call_args.args[0]
    assert (usage.user_id, usage.session_id) == (None, None)


def test_chat_records_failures_and_skips_invalid_input(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Retriever failures are recorded as errors; empty questions are not recorded at all."""
    monkeypatch.setattr(api, "_retriever", _Retriever(error=RuntimeError("db")))
    assert _post_chat().status_code == 502
    usage = recorded.record.call_args.args[0]
    assert (usage.status, usage.error_type) == ("error", "RuntimeError")

    recorded.reset_mock()
    assert _post_chat(content="   ").status_code == 400
    recorded.record.assert_not_called()


def test_chat_records_unavailable_service(monkeypatch: MonkeyPatch, recorded: MagicMock) -> None:
    """Requests arriving while the retriever is down count as unavailable."""
    monkeypatch.setattr(api, "_retriever", None)
    assert _post_chat().status_code == 503
    assert recorded.record.call_args.args[0].status == "unavailable"


# ---------- /api/admin/metrics ----------


@pytest.fixture
def admin_store(monkeypatch: MonkeyPatch):
    """Configure an admin token and a fake usage store."""
    monkeypatch.setenv("AWN_ADMIN_TOKEN", "s3cret")
    store = MagicMock()
    store.metrics.return_value = {"summary": {"requests": 3}}
    monkeypatch.setattr(admin_api, "_usage_store", store)
    return store


def test_admin_metrics_requires_configured_token(monkeypatch: MonkeyPatch, admin_store: MagicMock) -> None:
    """Without AWN_ADMIN_TOKEN the dashboard is disabled rather than open."""
    monkeypatch.delenv("AWN_ADMIN_TOKEN")
    response = TestClient(api.app).get("/api/admin/metrics", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    admin_store.metrics.assert_not_called()


@pytest.mark.parametrize("header", [None, "Bearer wrong", "s3cret", "Basic s3cret"])
def test_admin_metrics_rejects_bad_tokens(admin_store: MagicMock, header: str | None) -> None:
    """Missing, wrong, or non bearer credentials are rejected."""
    headers = {"Authorization": header} if header else {}
    response = TestClient(api.app).get("/api/admin/metrics", headers=headers)
    assert response.status_code == 401
    admin_store.metrics.assert_not_called()


def test_admin_metrics_returns_store_metrics_for_range(admin_store: MagicMock) -> None:
    """A valid token returns the store's metrics for the requested range in local time."""
    response = TestClient(api.app).get(
        "/api/admin/metrics", params={"range": "90d"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 200
    assert response.json() == {"summary": {"requests": 3}}
    admin_store.metrics.assert_called_once_with(90, "America/Los_Angeles")


def test_admin_metrics_rejects_unknown_range(admin_store: MagicMock) -> None:
    """Only the dashboard's preset ranges are accepted."""
    response = TestClient(api.app).get(
        "/api/admin/metrics", params={"range": "5y"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 422
