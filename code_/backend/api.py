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
from backend.chat_service import ChatServiceError, SavedChatService
from backend.conversation_context import ConversationContext
from backend.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    TurnConflictError,
)
from backend.history_service import HistoryService
from backend.models._chatbot_base import _BaseChatbot
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.station_catalog import StationList
from backend.weather_query import RequestedPoint
from backend.workflow.contracts import Source, WorkflowClassificationError, WorkflowTimeoutError
from backend.workflow.engine import LangGraphEngine
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import RateLimitError
from openrouter.errors import TooManyRequestsResponseError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("awn.api")
logging.basicConfig(level=logging.INFO)

# Keep the demo on the free router unless explicitly configured otherwise.
_DEFAULT_CHAT_MODEL = "openrouter/free"


class ChatMessage(BaseModel):
    """A single turn in the chat transcript sent from the frontend."""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=4000)


class WeatherLocation(BaseModel):
    """Accept an explicit station or a point from an older saved request."""

    model_config = ConfigDict(extra="forbid")
    point: RequestedPoint | None = None
    station_id: str | None = Field(default=None, strict=True, pattern=r"^[0-9]{1,20}$")

    @model_validator(mode="after")
    def one_location(self):
        """Reject conflicting selection methods."""
        if self.point is not None and self.station_id is not None:
            raise ValueError("Choose either a station or a point")
        return self


class ChatRequest(WeatherLocation):
    """Payload for POST /api/chat."""

    messages: list[ChatMessage] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounded_request(self):
        """Bound transcript size without discarding the active request."""
        if sum(len(message.content) for message in self.messages) > 32000:
            raise ValueError("Conversation exceeds 32000 characters")
        return self


class ChatResponse(BaseModel):
    """Payload returned by POST /api/chat."""

    reply: str
    model: str


class SavedChatRequest(WeatherLocation):
    """One accepted message, with stable IDs for retries."""

    conversation_id: UUID
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["weather", "history"] | None = None


class SavedChatResponse(ChatResponse):
    """Saved reply identity and the validated conversation context."""

    context: ConversationContext
    conversation_id: UUID
    request_id: UUID
    outcome: Literal["success", "history", "needs_clarification", "no_data"]
    sources: list[Source] = Field(default_factory=list)
    coverage: Literal["subset", "complete"] | None = None


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
_retriever: LangGraphEngine | None = None
_chatbot_model_name: str = ""
_embedding_model_name: str = ""


def _chat_model() -> str:
    return os.getenv("OPENROUTER_CHAT_MODEL", "").strip() or _DEFAULT_CHAT_MODEL


def _build_retriever() -> tuple[LangGraphEngine, _BaseChatbot, str, str]:
    required = ("OPENROUTER_API_KEY", "AWN_DB_USER", "AWN_DB_PASSWORD", "AWN_DB_HOST")
    if any(not os.getenv(name) for name in required):
        raise ValueError("The workflow requires model and AWN database configuration")
    model_name = os.getenv("OPENROUTER_WORKFLOW_MODEL", "").strip() or _chat_model()
    classifier_name = os.getenv("OPENROUTER_CLASSIFIER_MODEL", "").strip() or model_name
    settings = {
        "temperature": 0,
        "max_tokens": 3000,
        "request_timeout": 15000,
        "max_retries": 0,
        "reasoning": {"enabled": False, "effort": "none"},
    }
    chatbot = ChatbotOpenRouter({"model": model_name, **settings})
    classifier = ChatbotOpenRouter({"model": classifier_name, **settings})
    return LangGraphEngine(chatbot, classifier), chatbot, model_name, ""


def _latest_user_message(messages: list[ChatMessage]) -> str | None:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None


def _preceding_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return [message.model_dump() for message in messages[:index] if message.role != "system"]
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared model clients and the weather graph adapter."""
    global _chatbot, _retriever, _chatbot_model_name, _embedding_model_name
    global _history_service
    dotenv.load_dotenv()
    try:
        model_name = os.getenv("OPENROUTER_HISTORY_MODEL", "").strip() or _chat_model()
        model = ChatbotOpenRouter(
            {"model": model_name, "temperature": 0, "max_tokens": 1800, "request_timeout": 25000, "max_retries": 0}
        )
        _history_service = HistoryService(model, model_name)
    except Exception:
        logger.error("Failed to initialize conversation interpretation")
        _history_service = None
    try:
        _retriever, _chatbot, _chatbot_model_name, _embedding_model_name = _build_retriever()
        logger.info("LangGraph initialized with chat_model=%s", _chatbot_model_name)
    except Exception:
        logger.error("Failed to initialize LangGraph at startup")
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


def _retrieval_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, WorkflowClassificationError):
        return HTTPException(
            status_code=502,
            detail="The weather service could not interpret your question. Please try again or rephrase it.",
        )
    if isinstance(exc, WorkflowTimeoutError):
        return HTTPException(status_code=504, detail="The weather request took too long. Please try again.")
    if isinstance(exc, (RateLimitError, TooManyRequestsResponseError)):
        return HTTPException(
            status_code=503,
            detail="A model provider is rate-limiting requests. Please try again later.",
        )
    return HTTPException(
        status_code=502, detail="The weather service could not complete your request. Please try again."
    )


@app.exception_handler(ChatServiceError)
async def chat_service_error(request: Request, exc: ChatServiceError):
    """Distinguish saved history failures from weather retrieval failures."""
    name = "Saved conversation service" if exc.operation == "history" else "The weather service"
    if exc.reason == "unavailable":
        error = HTTPException(status_code=503, detail=f"{name} is temporarily unavailable. Please try again later.")
    elif exc.reason == "empty":
        error = HTTPException(status_code=502, detail=f"{name} returned an empty answer. Please try again.")
    else:
        error = _retrieval_error(exc.__cause__ or exc)
        if error.status_code == 502 and exc.operation == "history":
            error.detail = f"{name} could not complete your request. Please try again."
    logger.error("%s request failed (%s)", exc.operation, type(exc.__cause__ or exc).__name__)
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})


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


def _station_catalog(response: Response, point: RequestedPoint | None = None) -> StationList:
    response.headers["Cache-Control"] = "no-store"
    if _retriever is None:
        raise HTTPException(status_code=503, detail="Stations are temporarily unavailable. Please try again.")
    try:
        return _retriever.station_catalog(point)
    except Exception as exc:
        raise _retrieval_error(exc) from exc


@app.get("/api/stations", response_model=StationList)
def list_stations(response: Response) -> StationList:
    """List station names and counties from the cached AWN directory."""
    return _station_catalog(response)


@app.post("/api/stations/nearby", response_model=StationList)
def nearby_stations(payload: RequestedPoint, response: Response) -> StationList:
    """Use the browser point for sorting without persisting or echoing it."""
    return _station_catalog(response, payload)


def _saved_chat(payload: SavedChatRequest, request: Request, response: Response) -> SavedChatResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a weather related question.")
    owner = _owner(request, response)
    service = SavedChatService(_conversations, _history_service, _retriever, _chatbot_model_name)
    result = service.run(
        owner,
        payload.conversation_id,
        payload.request_id,
        question,
        point=payload.point,
        station_id=payload.station_id,
        mode=payload.mode or "weather",
    )
    return SavedChatResponse(
        **result.response(), conversation_id=payload.conversation_id, request_id=payload.request_id
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    """Readiness probe used by the frontend and ops tooling."""
    return {
        "status": "ok",
        "chatbot_ready": _chatbot is not None,
        "retriever_ready": _retriever is not None,
        "history_ready": _history_service is not None,
        "engine": "langgraph",
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
        selection = {"station_id": request.station_id} if request.station_id is not None else {}
        reply = _retriever.retrieve(
            question,
            point=request.point,
            history=_preceding_messages(request.messages),
            **selection,
        )
    except Exception as exc:
        logger.error("Retriever invocation failed (%s)", type(exc).__name__)
        raise _retrieval_error(exc) from exc

    if not reply.strip():
        raise HTTPException(
            status_code=502,
            detail="The weather service returned an empty answer. Please try again.",
        )

    return ChatResponse(reply=reply, model=_chatbot_model_name)
