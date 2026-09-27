/**
 *  HTTP client for the AWN backend.
 */

const API_BASE = import.meta.env?.VITE_API_BASE ?? "";
/** A single turn in the chat transcript, matching backend ChatMessage. */
export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatResponse {
  reply: string;
  model: string;
}

// Match ChatMessage and ChatRequest limits in backend/api.py.
const MAX_CHAT_MESSAGES = 40;
const MAX_MESSAGE_CHARACTERS = 4000;
const MAX_CHAT_CHARACTERS = 32000;

function recentChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const latestUser = messages.findLastIndex(message => message.role === "user");
  if (latestUser < 0) return messages;

  let start = latestUser;
  let characters = Array.from(messages[latestUser].content).length;
  for (let index = latestUser - 1; index >= 0 && latestUser - index < MAX_CHAT_MESSAGES; index--) {
    const length = Array.from(messages[index].content).length;
    if (length === 0 || length > MAX_MESSAGE_CHARACTERS || characters + length > MAX_CHAT_CHARACTERS) {
      break;
    }
    characters += length;
    start = index;
  }
  return messages.slice(start, latestUser + 1);
}

/** Error thrown by the API client so callers can surface a friendly message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseErrorDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return response.status === 422 ? body.detail.trim() || undefined : body.detail;
    }
    if (response.status === 422 && Array.isArray(body.detail)) {
      const details = body.detail
        .filter((error: unknown): error is { msg: string } =>
          typeof error === "object" && error !== null &&
          "msg" in error && typeof error.msg === "string",
        )
        .map(error => error.msg.trim())
        .filter(Boolean);
      return details.join("; ") || undefined;
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    return undefined;
  }
  return undefined;
}

/**
 * Build a user-friendly message for a failed HTTP response.
 */
function friendlyErrorMessage(status: number, detail: string | undefined): string {
  if (detail) {
    return detail;
  }
  if (status === 422) {
    return "The chat request is invalid. Please check your message and try again.";
  }
  if (status === 502 || status === 504) {
    return "The weather service could not complete your request. Please try again.";
  }
  if (status === 503) {
    return "The weather service is temporarily unavailable. Please try again later.";
  }
  return `Backend returned ${status}`;
}

/**
 * Send recent history through the latest user turn and return the assistant reply.
 *
 * @param messages   Ordered list of turns. Must contain at least one user turn.
 * @param signal     Optional AbortSignal to cancel the in-flight request.
 * @returns          The assistant's reply plus metadata about the model used.
 * @throws ApiError  On any non-2xx response or network failure.
 */
export async function sendChat(
  messages: ChatMessage[],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: recentChatMessages(messages) }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    throw new ApiError(0, "Network error — could not reach the AWN backend.");
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(response.status, friendlyErrorMessage(response.status, detail), detail);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    throw new ApiError(response.status, "The weather service returned an invalid response. Please try again.");
  }
  if (
    typeof body !== "object" || body === null ||
    !("reply" in body) || typeof body.reply !== "string" || !body.reply.trim() ||
    !("model" in body) || typeof body.model !== "string"
  ) {
    throw new ApiError(response.status, "The weather service returned an invalid response. Please try again.");
  }
  return { reply: body.reply, model: body.model };
}

/** GET /api/health */
export interface HealthResponse {
  status: string;
  chatbot_ready: boolean;
  retriever_ready: boolean;
  model: string | null;
  embedding_model: string | null;
  has_api_key: boolean;
  has_embedding_model: boolean;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/health`, { signal });
  if (!response.ok) {
    throw new ApiError(response.status, `Health check failed (${response.status})`);
  }
  return (await response.json()) as HealthResponse;
}
