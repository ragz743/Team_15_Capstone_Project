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
  if (status === 502 || status === 504) {
    return "The weather service could not complete your request. Please try again.";
  }
  if (status === 503) {
    return "The weather service is temporarily unavailable. Please try again later.";
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

export interface ConversationContext {
  station_ids: string[];
  county: string | null;
  start: string | null;
  end: string | null;
  subject: string | null;
}
export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface SavedMessage {
  id: string;
  request_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  status: "pending" | "completed" | "failed";
}
export interface SavedConversation extends ConversationSummary {
  context: ConversationContext;
  messages: SavedMessage[];
  next_before: number | null;
}

export interface SavedChatResponse extends ChatResponse {
  context: ConversationContext;
  conversation_id: string;
  request_id: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
function isContext(value: unknown): value is ConversationContext {
  if (!isObject(value)) return false;
  return Array.isArray(value.station_ids) && value.station_ids.every(id => typeof id === "string") &&
    ["county", "start", "end", "subject"].every(key => value[key] === null || typeof value[key] === "string");
}
const isDate = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const isId = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
function isSummary(value: unknown): value is ConversationSummary {
  return isObject(value) && isId(value.id) && typeof value.title === "string" &&
    isDate(value.created_at) && isDate(value.updated_at);
}
function isMessage(value: unknown): value is SavedMessage {
  return isObject(value) && typeof value.id === "string" && isId(value.request_id) &&
    ["user", "assistant"].includes(String(value.role)) && typeof value.content === "string" &&
    isDate(value.created_at) && ["pending", "completed", "failed"].includes(String(value.status));
}
function isConversation(value: unknown): value is SavedConversation {
  return isSummary(value) && "context" in value && isContext(value.context) &&
    "messages" in value && Array.isArray(value.messages) && value.messages.every(isMessage) &&
    "next_before" in value && (value.next_before === null || Number.isInteger(value.next_before));
}

function isSavedReply(value: unknown): value is SavedChatResponse {
  return isObject(value) && typeof value.reply === "string" && !!value.reply.trim() &&
    typeof value.model === "string" && isContext(value.context) && isId(value.conversation_id) && isId(value.request_id);
}

async function requestJson<T>(path: string, options: RequestInit, validate: (value: unknown) => value is T): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, credentials: "include" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Network error — could not reach the AWN backend.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (response.ok) throw new ApiError(response.status, "The weather service returned an invalid response. Please try again.");
  }
  if (!response.ok) {
    const detail = isObject(body) && typeof body.detail === "string" ? body.detail : undefined;
    const message = response.status === 503
      ? "The weather service is temporarily unavailable. Please try again later."
      : "The weather service could not complete your request. Please try again.";
    throw new ApiError(response.status, detail ?? message, detail);
  }
  if (!validate(body)) throw new ApiError(response.status, "The weather service returned an invalid response. Please try again.");
  return body;
}
function jsonPost(body: unknown, signal?: AbortSignal): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal };
}
export function sendSavedChat(conversationId: string, requestId: string, message: string, signal?: AbortSignal): Promise<SavedChatResponse> {
  return requestJson("/api/chat", jsonPost({ conversation_id: conversationId, request_id: requestId, message }, signal),
    (value): value is SavedChatResponse => isSavedReply(value) && "conversation_id" in value && value.conversation_id === conversationId &&
      "request_id" in value && value.request_id === requestId);
}
export async function listConversations(signal?: AbortSignal, before?: ConversationSummary): Promise<ConversationSummary[]> {
  const result = await requestJson(`/api/conversations${before ? `?before=${encodeURIComponent(before.updated_at)}&before_id=${encodeURIComponent(before.id)}` : ""}`, { signal },
    (value): value is { conversations: ConversationSummary[] } => isObject(value) && Array.isArray(value.conversations) && value.conversations.every(isSummary));
  return result.conversations;
}
export function createConversation(signal?: AbortSignal): Promise<ConversationSummary> {
  return requestJson("/api/conversations", jsonPost({}, signal), isSummary);
}
export function loadConversation(id: string, signal?: AbortSignal, before?: number): Promise<SavedConversation> {
  return requestJson(`/api/conversations/${encodeURIComponent(id)}${before ? `?before=${before}` : ""}`, { signal },
    (value): value is SavedConversation => isConversation(value) && value.id === id);
}
