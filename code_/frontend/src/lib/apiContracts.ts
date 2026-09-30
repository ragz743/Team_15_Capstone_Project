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

export interface HealthResponse {
  status: string;
  chatbot_ready: boolean;
  retriever_ready: boolean;
  model: string | null;
  embedding_model: string | null;
  has_api_key: boolean;
  has_embedding_model: boolean;
}

export interface RequestedPoint {
  latitude: number;
  longitude: number;
}

export type ChatMode = "weather" | "history";

export type ChatOutcome = "success" | "history" | "needs_clarification" | "no_data";

export interface ConversationContext {
  point?: RequestedPoint | null;
  data_kind?: "observation" | "forecast" | "both";
  question?: string | null;
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
  request_input?: { point?: RequestedPoint | null; mode?: ChatMode | null };
}
export interface SavedConversation extends ConversationSummary {
  context: ConversationContext;
  messages: SavedMessage[];
  next_before: number | null;
}

export interface SavedChatResponse extends ChatResponse {
  outcome: ChatOutcome;
  context: ConversationContext;
  conversation_id: string;
  request_id: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
function isPoint(value: unknown): value is RequestedPoint {
  return (
    isObject(value) &&
    typeof value.latitude === "number" &&
    Number.isFinite(value.latitude) &&
    typeof value.longitude === "number" &&
    Number.isFinite(value.longitude) &&
    Math.abs(value.latitude) <= 90 &&
    Math.abs(value.longitude) <= 180
  );
}
function isOutcome(value: unknown): value is ChatOutcome {
  return typeof value === "string" && ["success", "history", "needs_clarification", "no_data"].includes(value);
}
function isRequestInput(value: unknown): boolean {
  return (
    value === undefined ||
    (isObject(value) &&
      (value.point === undefined || value.point === null || isPoint(value.point)) &&
      (value.mode === undefined || value.mode === null || value.mode === "weather" || value.mode === "history"))
  );
}
function isContext(value: unknown): value is ConversationContext {
  if (!isObject(value)) return false;
  return (
    (value.point === undefined || value.point === null || isPoint(value.point)) &&
    (value.data_kind === undefined ||
      (typeof value.data_kind === "string" && ["observation", "forecast", "both"].includes(value.data_kind))) &&
    (value.question === undefined || value.question === null || typeof value.question === "string") &&
    Array.isArray(value.station_ids) &&
    value.station_ids.every((id) => typeof id === "string") &&
    ["county", "start", "end", "subject"].every((key) => value[key] === null || typeof value[key] === "string")
  );
}
const isDate = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const isId = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
export function isSummary(value: unknown): value is ConversationSummary {
  return (
    isObject(value) &&
    isId(value.id) &&
    typeof value.title === "string" &&
    isDate(value.created_at) &&
    isDate(value.updated_at)
  );
}
function isMessage(value: unknown): value is SavedMessage {
  return (
    isObject(value) &&
    typeof value.id === "string" &&
    isId(value.request_id) &&
    typeof value.role === "string" &&
    ["user", "assistant"].includes(value.role) &&
    typeof value.content === "string" &&
    isDate(value.created_at) &&
    typeof value.status === "string" &&
    ["pending", "completed", "failed"].includes(value.status) &&
    isRequestInput(value.request_input)
  );
}
export function isConversation(value: unknown): value is SavedConversation {
  return (
    isSummary(value) &&
    "context" in value &&
    isContext(value.context) &&
    "messages" in value &&
    Array.isArray(value.messages) &&
    value.messages.every(isMessage) &&
    "next_before" in value &&
    (value.next_before === null ||
      (typeof value.next_before === "number" && Number.isInteger(value.next_before) && value.next_before > 0))
  );
}

export function isSavedReply(value: unknown): value is SavedChatResponse {
  return (
    isObject(value) &&
    isChatReply(value) &&
    isOutcome(value.outcome) &&
    isContext(value.context) &&
    isId(value.conversation_id) &&
    isId(value.request_id)
  );
}

export function isChatReply(value: unknown): value is ChatResponse {
  return (
    isObject(value) &&
    typeof value.reply === "string" &&
    !!value.reply.trim() &&
    typeof value.model === "string"
  );
}

export function isConversationList(value: unknown): value is { conversations: ConversationSummary[] } {
  return isObject(value) && Array.isArray(value.conversations) && value.conversations.every(isSummary);
}
