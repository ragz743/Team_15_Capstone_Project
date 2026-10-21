"""FastAPI HTTP server exposing the AWN chatbot to the frontend.

Run locally (from repo root, with venv active):
    uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import dotenv
from backend.analytics import admin_api
from backend.analytics.metering import MeteredEmbedding, RequestUsage
from backend.analytics.usage_store import UsageStore, UsageTracker
from backend.databases.pgvector import PgVectorConnection
from backend.models._chatbot_base import _BaseChatbot
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.models.embedding_openrouter import EmbeddingOpenRouter
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import RateLimitError
from openrouter.errors import TooManyRequestsResponseError
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("awn.api")
logging.basicConfig(level=logging.INFO)

# Default OpenRouter chat model
# free tier model keeps this safe for prototyping without burning credits.
# NOTE: OpenRouter rotates the free-tier catalog; if this model 404s, pick
# another ":free" entry from https://openrouter.ai/api/v1/models.
_DEFAULT_CHAT_MODEL = "openai/gpt-oss-20b:free"

# Optional anonymous ids the chat frontend sends so the admin dashboard can count users and sessions.
_CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ChatMessage(BaseModel):
    """A single turn in the chat transcript sent from the frontend."""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Payload for POST /api/chat."""

    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    filter: dict[str, str] | None = None

    @model_validator(mode="after")
    def bounded_request(self):
        """Bound transcript size without discarding the active request."""
        if sum(len(message.content) for message in self.messages) > 32000:
            raise ValueError("Conversation exceeds 32000 characters")
        if self.filter and (len(self.filter) > 4 or any(len(v) > 100 for v in self.filter.values())):
            raise ValueError("Invalid metadata filter")
        return self


class ChatResponse(BaseModel):
    """Payload returned by POST /api/chat."""

    reply: str
    model: str


# initialized at startup.
_chatbot: _BaseChatbot | None = None
_retriever: Retriever | None = None
_chatbot_model_name: str = ""
_embedding_model_name: str = ""
_usage_tracker: UsageTracker = UsageTracker(None)


def _build_retriever() -> tuple[Retriever, _BaseChatbot, str, str]:
    if not os.getenv("OPENROUTER_API_KEY"):
        logger.warning("OPENROUTER_API_KEY not set - /api/chat will fail until configured")

    chat_model_name = os.getenv("OPENROUTER_CHAT_MODEL", _DEFAULT_CHAT_MODEL)
    embedding_model_name = os.getenv("OPENROUTER_EMBEDDING_MODEL")
    if not embedding_model_name:
        msg = "OPENROUTER_EMBEDDING_MODEL must be set to initialize retrieval"
        raise ValueError(msg)

    temperature = float(os.getenv("OPENROUTER_CHAT_TEMPERATURE", "0"))

    # Builds embedding model and chatbot
    embedding_model = MeteredEmbedding(EmbeddingOpenRouter(embedding_model_name), embedding_model_name)
    chatbot = ChatbotOpenRouter({"model": chat_model_name, "temperature": temperature})

    # Builds all three stores: daily_index, live_index, forecast_index
    stores = [
        PgVectorStore(embedding_model, table="daily_index"),
        PgVectorStore(embedding_model, table="live_index", staleness_days=30),
        PgVectorStore(embedding_model, table="forecast_index", staleness_days=2),
    ]
    retriever = Retriever(stores, chatbot)

    return retriever, chatbot, chat_model_name, embedding_model_name


def _build_usage_store() -> UsageStore | None:
    if os.getenv("AWN_USAGE_TRACKING", "true").lower() == "false":
        logger.info("Usage tracking disabled by AWN_USAGE_TRACKING")
        return None

    # short timeout so an unreachable database delays a chat request by seconds, not minutes
    store = UsageStore(lambda: PgVectorConnection(connect_timeout=3).conn)
    try:
        store.ensure_schema()
    except Exception:
        # keep the store, it retries on the next write once the database is reachable
        logger.warning("Usage tables could not be created yet, will retry on first use", exc_info=True)
    return store


def _client_id(value: str | None) -> str | None:
    return value if value is not None and _CLIENT_ID_PATTERN.fullmatch(value) else None


def _latest_user_message(messages: list[ChatMessage]) -> str | None:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the retriever once at process start."""
    global _chatbot, _retriever, _chatbot_model_name, _embedding_model_name, _usage_tracker
    dotenv.load_dotenv()
    usage_store = _build_usage_store()
    admin_api.set_usage_store(usage_store)
    _usage_tracker = UsageTracker(usage_store)
    try:
        _retriever, _chatbot, _chatbot_model_name, _embedding_model_name = _build_retriever()
        logger.info(
            "Retriever initialized with chat_model=%s embedding_model=%s",
            _chatbot_model_name,
            _embedding_model_name,
        )
    except Exception:
        logger.exception("Failed to initialize retriever at startup")
        _chatbot = None
        _retriever = None
        _chatbot_model_name = ""
        _embedding_model_name = ""
    yield
    if usage_store is not None:
        usage_store.close()


app = FastAPI(
    title="AWN AI API",
    version="0.1.0",
    description="Prototype HTTP API bridging the AWN React frontend to the LLM backend.",
    lifespan=lifespan,
)

# Dev only permissive CORS, NOT for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(admin_api.router)


def _retrieval_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (RateLimitError, TooManyRequestsResponseError)):
        return HTTPException(
            status_code=503,
            detail="A model provider is rate-limiting requests. Please try again later.",
        )
    return HTTPException(
        status_code=502, detail="The weather service could not complete your request. Please try again."
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    """Readiness probe used by the frontend and ops tooling."""
    return {
        "status": "ok",
        "chatbot_ready": _chatbot is not None,
        "retriever_ready": _retriever is not None,
        "model": _chatbot_model_name or None,
        "embedding_model": _embedding_model_name or None,
        "has_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
        "has_embedding_model": bool(os.getenv("OPENROUTER_EMBEDDING_MODEL")),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    x_awn_user_id: Annotated[str | None, Header()] = None,
    x_awn_session_id: Annotated[str | None, Header()] = None,
) -> ChatResponse:
    """Endpoint for the frontend to send a conversation and receive a reply."""
    with _usage_tracker.track(_client_id(x_awn_user_id), _client_id(x_awn_session_id)) as usage:
        return _answer(request, usage)


def _answer(request: ChatRequest, usage: RequestUsage) -> ChatResponse:
    if _retriever is None:
        usage.status = "unavailable"
        raise HTTPException(
            status_code=503,
            detail="The weather service is temporarily unavailable. Please try again later.",
        )

    question = _latest_user_message(request.messages)
    if question is None:
        usage.record = False
        raise HTTPException(status_code=400, detail="At least one user message is required.")

    question = question.strip()
    if not question:
        usage.record = False
        raise HTTPException(status_code=400, detail="Please enter a weather related question.")

    try:
        reply = _retriever.retrieve(question, filter=request.filter)
    except Exception as exc:
        logger.error("Retriever invocation failed (%s)", type(exc).__name__)
        usage.status = "rate_limited" if isinstance(exc, (RateLimitError, TooManyRequestsResponseError)) else "error"
        usage.error_type = type(exc).__name__
        raise _retrieval_error(exc) from exc

    if not reply.strip():
        usage.status = "empty"
        raise HTTPException(
            status_code=502,
            detail="The weather service returned an empty answer. Please try again.",
        )

    usage.status = "ok"
    return ChatResponse(reply=reply, model=_chatbot_model_name)
