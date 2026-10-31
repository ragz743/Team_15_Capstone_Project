"""Capture the LLM calls made while answering a chat request.

Chat model calls are captured with a LangChain callback handler that is attached to every
LangChain model invoked inside `metered(usage)`, so chatbot classes need no changes. Embedding
calls do not emit LangChain callbacks, so the embedding model is wrapped in `MeteredEmbedding`.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, override
from uuid import UUID, uuid4

from backend.models._embedding_base import _BaseEmbedding
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook

RequestStatus = Literal["ok", "empty", "error", "rate_limited", "unavailable"]

# rough characters per token, only used when a provider does not report token usage
_CHARS_PER_TOKEN = 4


def estimate_tokens(chars: int) -> int:
    """Estimate a token count from a character count."""
    return math.ceil(chars / _CHARS_PER_TOKEN)


@dataclass
class LlmCall:
    """A single model call made while answering a request."""

    kind: Literal["chat", "embedding"]
    model: str
    called_at: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False
    latency_ms: int | None = None
    succeeded: bool = True
    requested_model: str | None = None  # configured model, when the provider answered under another name
    cost_usd: float | None = None  # cost billed by the provider (OpenRouter reports it), None when not reported


@dataclass
class RequestUsage:
    """Everything recorded about one chat request."""

    user_id: str | None = None
    session_id: str | None = None
    request_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int = 0
    status: RequestStatus | None = None
    error_type: str | None = None
    record: bool = True  # set False for requests that should not count, e.g. invalid input
    calls: list[LlmCall] = field(default_factory=list)


class _LlmCallRecorder(BaseCallbackHandler):
    """LangChain callback handler appending each chat model call to a RequestUsage."""

    def __init__(self, usage: RequestUsage) -> None:
        self.usage = usage
        self._lock = threading.Lock()
        self._started: dict[UUID, tuple[float, str, int]] = {}  # run_id -> (start, model, prompt chars)

    @override
    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any) -> None:
        chars = sum(len(str(m.content)) for batch in messages for m in batch)
        self._start(kwargs["run_id"], _model_name(kwargs), chars)

    @override
    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        self._start(kwargs["run_id"], _model_name(kwargs), sum(len(p) for p in prompts))

    @override
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        started, model, prompt_chars = self._finish(kwargs["run_id"])
        input_tokens, output_tokens, estimated = _token_usage(response, prompt_chars)
        self._append(
            LlmCall(
                kind="chat",
                model=_response_model_name(response) or model,
                requested_model=model,
                cost_usd=_reported_cost(response),
                called_at=datetime.now(UTC),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tokens_estimated=estimated,
                latency_ms=_elapsed_ms(started),
            )
        )

    @override
    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        started, model, _ = self._finish(kwargs["run_id"])
        self._append(
            LlmCall(
                kind="chat",
                model=model,
                called_at=datetime.now(UTC),
                latency_ms=_elapsed_ms(started),
                succeeded=False,
            )
        )

    def add_embedding_call(self, model: str, chars: int, latency_ms: int, succeeded: bool) -> None:
        """Record an embedding call made by MeteredEmbedding."""
        self._append(
            LlmCall(
                kind="embedding",
                model=model,
                called_at=datetime.now(UTC),
                input_tokens=estimate_tokens(chars),
                tokens_estimated=True,
                latency_ms=latency_ms,
                succeeded=succeeded,
            )
        )

    def _start(self, run_id: UUID, model: str, prompt_chars: int) -> None:
        with self._lock:
            self._started[run_id] = (time.perf_counter(), model, prompt_chars)

    def _finish(self, run_id: UUID) -> tuple[float | None, str, int]:
        with self._lock:
            return self._started.pop(run_id, (None, "unknown", 0))

    def _append(self, call: LlmCall) -> None:
        with self._lock:
            self.usage.calls.append(call)


# Holds the recorder for the request currently being answered. Registered once as an inheritable
# configure hook so every LangChain model invoked while it is set reports to the recorder.
_active_recorder: ContextVar[_LlmCallRecorder | None] = ContextVar("awn_llm_call_recorder", default=None)
register_configure_hook(_active_recorder, inheritable=True)


@contextmanager
def metered(usage: RequestUsage) -> Iterator[RequestUsage]:
    """Record every model call made inside the block into `usage.calls`."""
    token = _active_recorder.set(_LlmCallRecorder(usage))
    try:
        yield usage
    finally:
        _active_recorder.reset(token)


class MeteredEmbedding(_BaseEmbedding):
    """Wraps an embedding model so each embedding call is recorded for the active request."""

    def __init__(self, inner: _BaseEmbedding, model_name: str) -> None:
        """Wrap `inner`, reporting its calls under `model_name`."""
        self._inner = inner
        self._model_name = model_name

    @override
    def embed_document(self, document: Document) -> tuple[list[float], Document]:
        with self._metered_call(len(document.page_content)):
            return self._inner.embed_document(document)

    @override
    def embed_documents(self, documents: list[Document]) -> list[tuple[list[float], Document]]:
        with self._metered_call(sum(len(d.page_content) for d in documents)):
            return self._inner.embed_documents(documents)

    @contextmanager
    def _metered_call(self, chars: int) -> Iterator[None]:
        recorder = _active_recorder.get()
        started = time.perf_counter()
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            if recorder is not None:
                recorder.add_embedding_call(self._model_name, chars, _elapsed_ms(started) or 0, succeeded)


def _elapsed_ms(started: float | None) -> int | None:
    return None if started is None else round((time.perf_counter() - started) * 1000)


def _model_name(callback_kwargs: dict[str, Any]) -> str:
    """Find the requested model name in the metadata LangChain passes to start callbacks."""
    metadata = callback_kwargs.get("metadata") or {}
    params = callback_kwargs.get("invocation_params") or {}
    return str(metadata.get("ls_model_name") or params.get("model") or params.get("model_name") or "unknown")


def _response_model_name(response: LLMResult) -> str | None:
    """Return the model the provider says answered, which can differ from the requested one."""
    for generations in response.generations:
        for generation in generations:
            if isinstance(generation, ChatGeneration):
                name = generation.message.response_metadata.get("model_name")
                if name:
                    return str(name)
    return None


def _reported_cost(response: LLMResult) -> float | None:
    """Return the cost the provider billed for this call, when it reports one (OpenRouter does)."""
    costs = [
        float(generation.message.response_metadata["cost"])
        for generations in response.generations
        for generation in generations
        if isinstance(generation, ChatGeneration) and generation.message.response_metadata.get("cost") is not None
    ]
    return sum(costs) if costs else None


def _token_usage(response: LLMResult, prompt_chars: int) -> tuple[int, int, bool]:
    """Return (input tokens, output tokens, estimated) for a finished call."""
    input_tokens = output_tokens = 0
    reported = False
    output_chars = 0
    for generations in response.generations:
        for generation in generations:
            output_chars += len(generation.text)
            message = generation.message if isinstance(generation, ChatGeneration) else None
            usage = message.usage_metadata if isinstance(message, AIMessage) else None
            if usage:
                input_tokens += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)
                reported = True

    if not reported:
        token_usage = (response.llm_output or {}).get("token_usage") or {}
        if token_usage:
            return token_usage.get("prompt_tokens", 0), token_usage.get("completion_tokens", 0), False
        return estimate_tokens(prompt_chars), estimate_tokens(output_chars), True

    return input_tokens, output_tokens, False
