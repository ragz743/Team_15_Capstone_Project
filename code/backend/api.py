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


# Global chatbot instance, initialized at startup and shared across requests.
_chatbot: _BaseChatbot | None = None
_chatbot_model_name: str = ""


def _build_chatbot() -> tuple[_BaseChatbot, str]:
    if not os.getenv("OPENROUTER_API_KEY"):
        logger.warning("OPENROUTER_API_KEY not set - /api/chat will fail until configured")

    model_name = os.getenv("OPENROUTER_CHAT_MODEL", _DEFAULT_CHAT_MODEL)
    temperature = float(os.getenv("OPENROUTER_CHAT_TEMPERATURE", "0"))

    chatbot = ChatbotOpenRouter({"model": model_name, "temperature": temperature})
    return chatbot, model_name


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the chatbot once at process start."""
    global _chatbot, _chatbot_model_name
    dotenv.load_dotenv()
    try:
        _chatbot, _chatbot_model_name = _build_chatbot()
        logger.info("Chatbot initialized with model=%s", _chatbot_model_name)
    except Exception:
        logger.exception("Failed to initialize chatbot at startup")
        _chatbot = None
    yield


app = FastAPI(
    title="AWN AI API",
    version="0.1.0",
    description="Prototype HTTP API bridging the AWN React frontend to the LLM backend.",
    lifespan=lifespan,
)

# Dev-only permissive CORS.
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
        "model": _chatbot_model_name or None,
        "has_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Endpoint for the frontend to send a conversation and receive a reply."""
    if _chatbot is None:
        raise HTTPException(
            status_code=503,
            detail="Chatbot is not initialized. Check server logs and OPENROUTER_API_KEY.",
        )

    flattened: list[str] = []
    for msg in request.messages:
        if msg.role == "user":
            flattened.append(msg.content)
        else:
            flattened.append(f"[{msg.role}] {msg.content}")

    try:
        reply = _chatbot.invoke(flattened)
    except Exception as exc:
        logger.exception("Chatbot invocation failed")
        raise HTTPException(status_code=502, detail=f"Upstream LLM error: {exc}") from exc

    return ChatResponse(reply=reply, model=_chatbot_model_name)
