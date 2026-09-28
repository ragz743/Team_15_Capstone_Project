import { API_BASE, ApiError, jsonPost, requestJson } from "./http.ts";
import {
  isChatReply,
  isConversation,
  isConversationList,
  isSavedReply,
  isSummary,
  type ChatMessage,
  type ChatResponse,
  type ConversationSummary,
  type HealthResponse,
  type RequestedPoint,
  type SavedChatResponse,
  type SavedConversation,
} from "./apiContracts.ts";

export { ApiError } from "./http.ts";
export type * from "./apiContracts.ts";

// Match ChatMessage and ChatRequest limits in backend/api.py.
const MAX_CHAT_MESSAGES = 40;
const MAX_MESSAGE_CHARACTERS = 4000;
const MAX_CHAT_CHARACTERS = 32000;

function recentChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const latestUser = messages.findLastIndex((message) => message.role === "user");
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

export async function sendChat(
  messages: ChatMessage[],
  signal?: AbortSignal,
  point?: RequestedPoint | null,
): Promise<ChatResponse> {
  const result = await requestJson(
    "/api/chat",
    {
      ...jsonPost({ messages: recentChatMessages(messages), ...(point ? { point } : {}) }, signal),
      credentials: "same-origin",
    },
    isChatReply,
  );
  return { reply: result.reply, model: result.model };
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/health`, { signal });
  if (!response.ok) {
    throw new ApiError(response.status, `Health check failed (${response.status})`);
  }
  return (await response.json()) as HealthResponse;
}

export function sendSavedChat(
  conversationId: string,
  requestId: string,
  message: string,
  signal?: AbortSignal,
  point?: RequestedPoint | null,
): Promise<SavedChatResponse> {
  return requestJson(
    "/api/chat",
    jsonPost({ conversation_id: conversationId, request_id: requestId, message, ...(point ? { point } : {}) }, signal),
    (value): value is SavedChatResponse =>
      isSavedReply(value) &&
      value.conversation_id === conversationId &&
      value.request_id === requestId,
  );
}
export async function listConversations(
  signal?: AbortSignal,
  before?: ConversationSummary,
): Promise<ConversationSummary[]> {
  const result = await requestJson(
    `/api/conversations${before ? `?before=${encodeURIComponent(before.updated_at)}&before_id=${encodeURIComponent(before.id)}` : ""}`,
    { signal },
    isConversationList,
  );
  return result.conversations;
}
export function createConversation(signal?: AbortSignal): Promise<ConversationSummary> {
  return requestJson("/api/conversations", jsonPost({}, signal), isSummary);
}
export function loadConversation(id: string, signal?: AbortSignal, before?: number): Promise<SavedConversation> {
  return requestJson(
    `/api/conversations/${encodeURIComponent(id)}${before ? `?before=${before}` : ""}`,
    { signal },
    (value): value is SavedConversation => isConversation(value) && value.id === id,
  );
}
