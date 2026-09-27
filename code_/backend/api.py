"""FastAPI HTTP server exposing the AWN chatbot to the frontend.

Run locally (from repo root, with venv active):
    uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import dotenv
from backend.models._chatbot_base import _BaseChatbot
from backend.models.chatbot_openrouter import ChatbotOpenRouter
from backend.models.embedding_openrouter import EmbeddingOpenRouter
from backend.retriever import Retriever
from backend.vector_store import PgVectorStore
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Payload for POST /api/chat."""

    messages: list[ChatMessage] = Field(min_length=1)


class ChatResponse(BaseModel):
    """Payload returned by POST /api/chat."""

    reply: str
    model: str


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

    embedding_model = EmbeddingOpenRouter(embedding_model_name)
    vector_store = PgVectorStore(embedding_model)
    chatbot = ChatbotOpenRouter({"model": chat_model_name, "temperature": temperature})
    retriever = Retriever(vector_store, chatbot)
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
    dotenv.load_dotenv()
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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
def chat(request: ChatRequest) -> ChatResponse:
    """Endpoint for the frontend to send a conversation and receive a reply."""
    if _retriever is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Retriever is not initialized. Check server logs, pgvector, "
                "OPENROUTER_API_KEY, and OPENROUTER_EMBEDDING_MODEL."
            ),
        )

    question = _latest_user_message(request.messages)
    if question is None:
        raise HTTPException(status_code=400, detail="At least one user message is required.")

    try:
        reply = _retriever.retrieve(question)
    except Exception as exc:
        logger.exception("Retriever invocation failed")
        raise HTTPException(status_code=502, detail=f"Retrieval error: {exc}") from exc

    return ChatResponse(reply=reply, model=_chatbot_model_name)
