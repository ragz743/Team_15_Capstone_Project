/**
 *  HTTP client for the AWN backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
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
      return body.detail;
    }
  } catch {
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
  if (status === 502 || status === 504) {
    return "Cannot reach the AWN backend. Is uvicorn running on port 8000?";
  }
  return `Backend returned ${status}`;
}

/**
 * Send the conversation history to the backend and return the assistant reply.
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
      body: JSON.stringify({ messages }),
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

  return (await response.json()) as ChatResponse;
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
