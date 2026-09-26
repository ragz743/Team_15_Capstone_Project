"""FastAPI HTTP server exposing the AWN chatbot to the frontend.

Run locally (from repo root, with venv active):
    uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

import dotenv
import psycopg
from backend.chat_turn import AnsweredTurn, PreparedChatTurn
from backend.conversation_context import TIMEZONE, ConversationContext
from backend.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    TurnConflictError,
)
from backend.history_service import HistoryService
from backend.models._chatbot_base import _BaseChatbot
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.models.embedding_openrouter import EmbeddingOpenRouter
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import RateLimitError
from openrouter.errors import TooManyRequestsResponseError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("awn.api")
logging.basicConfig(level=logging.INFO)

# Default OpenRouter chat model
# free tier model keeps this safe for prototyping without burning credits.
# NOTE: OpenRouter rotates the free-tier catalog; if this model 404s, pick
# another ":free" entry from https://openrouter.ai/api/v1/models.
_DEFAULT_CHAT_MODEL = "openai/gpt-oss-20b:free"


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


class SavedChatRequest(BaseModel):
    """One accepted message, with stable IDs for retries."""

    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)


class SavedChatResponse(ChatResponse):
    """Saved reply identity and the validated conversation context."""

    context: ConversationContext
    conversation_id: UUID
    request_id: UUID
    outcome: Literal["success", "history", "needs_clarification", "no_data"]


_conversations = ConversationStore()
_history_service: HistoryService | None = None
_COOKIE = "awn_browser"
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("AWN_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]


# initialized at startup.
_chatbot: _BaseChatbot | None = None
_retriever: Retriever | None = None
_chatbot_model_name: str = ""
_embedding_model_name: str = ""


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
    embedding_model = EmbeddingOpenRouter(embedding_model_name)
    chatbot = ChatbotOpenRouter({"model": chat_model_name, "temperature": temperature})

    # Builds all three stores: daily_index, live_index, forecast_index
    stores = [
        PgVectorStore(embedding_model, table="daily_index"),
        PgVectorStore(embedding_model, table="live_index", staleness_days=30),
        PgVectorStore(embedding_model, table="forecast_index", staleness_days=2),
    ]
    retriever = Retriever(stores, chatbot)

    return retriever, chatbot, chat_model_name, embedding_model_name


def _latest_user_message(messages: list[ChatMessage]) -> str | None:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the retriever once at process start."""
    global _chatbot, _retriever, _chatbot_model_name, _embedding_model_name
    global _history_service
    dotenv.load_dotenv()
    try:
        model_name = os.getenv("OPENROUTER_HISTORY_MODEL") or os.getenv("OPENROUTER_CHAT_MODEL", _DEFAULT_CHAT_MODEL)
        model = ChatbotOpenRouter(
            {"model": model_name, "temperature": 0, "max_tokens": 1800, "request_timeout": 25000, "max_retries": 0}
        )
        _history_service = HistoryService(model, model_name)
    except Exception:
        logger.error("Failed to initialize conversation interpretation")
        _history_service = None
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


app = FastAPI(
    title="AWN AI API",
    version="0.1.0",
    description="Prototype HTTP API bridging the AWN React frontend to the LLM backend.",
    lifespan=lifespan,
)

# Dev only permissive CORS, NOT for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _retrieval_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (RateLimitError, TooManyRequestsResponseError)):
        if "free-models-per-day" in str(exc):
            return HTTPException(
                status_code=503,
                detail=(
                    "The model provider's daily free allowance has been reached. "
                    "Please try again after the allowance resets."
                ),
            )
        return HTTPException(
            status_code=503,
            detail="The answer provider is rate-limiting requests. Please try again later.",
        )
    return HTTPException(
        status_code=502, detail="The weather service could not complete your request. Please try again."
    )


@app.exception_handler(ConversationNotFoundError)
async def conversation_not_found(request: Request, exc: ConversationNotFoundError):
    """Use the same response for missing and foreign conversation IDs."""
    return JSONResponse(status_code=404, content={"detail": "Conversation not found."})


@app.exception_handler(TurnConflictError)
async def turn_conflict(request: Request, exc: TurnConflictError):
    """Let callers retry or reload without duplicating a turn."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(psycopg.Error)
async def conversation_database_error(request: Request, exc: psycopg.Error):
    """Keep database configuration and credentials out of client responses."""
    logger.error("Conversation database unavailable (%s)", type(exc).__name__)
    return JSONResponse(
        status_code=503, content={"detail": "Saved conversations are temporarily unavailable. Please try again."}
    )


def _owner(request: Request, response: Response, *, create: bool = False) -> UUID:
    origin = request.headers.get("origin")
    same_origin = str(request.base_url).rstrip("/")
    if origin and origin != same_origin and origin not in _ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="This origin is not allowed.")
    owner = _conversations.owner(request.cookies.get(_COOKIE))
    if owner is None:
        if not create:
            raise ConversationNotFoundError
        owner, token = _conversations.create_owner()
        response.set_cookie(
            _COOKIE,
            token,
            max_age=365 * 86400,
            httponly=True,
            samesite="lax",
            path="/api",
            secure=request.url.scheme == "https" or os.getenv("AWN_COOKIE_SECURE") == "true",
        )
    response.headers["Cache-Control"] = "no-store"
    return owner


@app.get("/api/conversations")
def list_conversations(
    request: Request, response: Response, before: AwareDatetime | None = None, before_id: UUID | None = None
):
    """List this browser's saved conversations and initialize its identity if needed."""
    owner = _owner(request, response, create=True)
    if (before is None) != (before_id is None):
        raise HTTPException(status_code=422, detail="The history cursor needs both before and before_id.")
    return {"conversations": _conversations.list_conversations(owner, before=before, before_id=before_id)}


@app.post("/api/conversations", status_code=201)
def create_conversation(request: Request, response: Response):
    """Start a fresh context without deleting earlier conversations."""
    return _conversations.create(_owner(request, response, create=True))


@app.get("/api/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID, request: Request, response: Response, before: int | None = Query(default=None, ge=1)
):
    """Resume an owned conversation with dated, ordered messages."""
    return _conversations.get(_owner(request, response), conversation_id, before=before)


def _saved_chat(payload: SavedChatRequest, request: Request, response: Response) -> SavedChatResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a weather related question.")
    owner = _owner(request, response)
    turn = _conversations.begin(owner, payload.conversation_id, payload.request_id, question)
    if turn.completed is not None:
        return SavedChatResponse(
            **turn.completed,
            context=turn.context,
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
        )
    try:
        prepared = turn.prepared
        if prepared is None:
            if _history_service is None:
                raise HTTPException(status_code=503, detail="Conversation understanding is temporarily unavailable.")
            day = turn.requested_at.astimezone(TIMEZONE).date()
            history = _history_service.prepare(
                _conversations, owner, payload.conversation_id, question, accepted_at=turn.requested_at
            )
            if history.snapshot is not None:
                prepared = PreparedChatTurn(
                    outcome="history",
                    question=question,
                    context=turn.context,
                    history=history.snapshot,
                )
            elif history.reply is not None:
                prepared = PreparedChatTurn(
                    outcome="needs_clarification" if history.intent.action == "clarify" else "history",
                    question=question,
                    context=turn.context,
                    reply=history.reply,
                )
            else:
                if _retriever is None:
                    raise HTTPException(
                        status_code=503,
                        detail="The weather service is temporarily unavailable. Please try again later.",
                    )
                context = turn.context
                if history.intent.action == "reuse":
                    question = history.intent.weather_question or question
                    context = history.context or context
                prepared = _retriever.prepare_turn(question, context, today=day)
            _conversations.prepare(owner, payload.conversation_id, payload.request_id, turn.attempt_id, prepared)
        context = prepared.context
        if prepared.history is not None:
            if _history_service is None:
                raise HTTPException(status_code=503, detail="Saved conversation answers are temporarily unavailable.")
            reply = _history_service.answer(prepared.question, prepared.history)
            result = AnsweredTurn(reply=reply, outcome="history")
            model = _history_service.model_name
        elif prepared.reply is not None:
            reply = prepared.reply
            assert prepared.outcome != "weather"
            result = AnsweredTurn(reply=reply, outcome=prepared.outcome)
            model = "saved-history" if prepared.outcome == "history" else _chatbot_model_name
        else:
            if _retriever is None:
                raise HTTPException(
                    status_code=503, detail="The weather service is temporarily unavailable. Please try again later."
                )
            result = _retriever.answer_result(prepared)
            reply = result.reply
            model = _chatbot_model_name
        if not reply.strip():
            raise HTTPException(
                status_code=502, detail="The weather service returned an empty answer. Please try again."
            )
        metadata = result.model_dump(mode="json", exclude={"reply"})
        _conversations.complete(
            owner,
            payload.conversation_id,
            payload.request_id,
            turn.attempt_id,
            reply,
            model,
            context,
            metadata=metadata,
        )
        return SavedChatResponse(
            reply=reply,
            model=model,
            context=context,
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
            **metadata,
        )
    except Exception as exc:
        try:
            _conversations.fail(owner, payload.conversation_id, payload.request_id, turn.attempt_id)
        except psycopg.Error:
            logger.error("Could not record failed conversation turn")
        if isinstance(exc, (HTTPException, ConversationNotFoundError, TurnConflictError, psycopg.Error)):
            raise
        logger.error("Saved conversation request failed (%s)", type(exc).__name__)
        raise _retrieval_error(exc) from exc


@app.get("/api/health")
def health() -> dict[str, object]:
    """Readiness probe used by the frontend and ops tooling."""
    return {
        "status": "ok",
        "chatbot_ready": _chatbot is not None,
        "retriever_ready": _retriever is not None,
        "history_ready": _history_service is not None,
        "model": _chatbot_model_name or None,
        "embedding_model": _embedding_model_name or None,
        "has_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
        "has_embedding_model": bool(os.getenv("OPENROUTER_EMBEDDING_MODEL")),
    }


@app.post("/api/chat", response_model=SavedChatResponse | ChatResponse)
def chat(request: ChatRequest | SavedChatRequest, raw: Request, response: Response) -> SavedChatResponse | ChatResponse:
    """Endpoint for the frontend to send a conversation and receive a reply."""
    if isinstance(request, SavedChatRequest):
        return _saved_chat(request, raw, response)
    if _retriever is None:
        raise HTTPException(
            status_code=503,
            detail="The weather service is temporarily unavailable. Please try again later.",
        )

    question = _latest_user_message(request.messages)
    if question is None:
        raise HTTPException(status_code=400, detail="At least one user message is required.")

    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a weather related question.")

    try:
        reply = _retriever.retrieve(question, filter=request.filter)
    except Exception as exc:
        logger.error("Retriever invocation failed (%s)", type(exc).__name__)
        raise _retrieval_error(exc) from exc

    if not reply.strip():
        raise HTTPException(
            status_code=502,
            detail="The weather service returned an empty answer. Please try again.",
        )

    return ChatResponse(reply=reply, model=_chatbot_model_name)
