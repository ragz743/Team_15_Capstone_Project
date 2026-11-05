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

export interface PublicStation {
  id: string;
  name: string;
  county: string;
  distance_km: number | null;
}

export interface StationCatalog {
  stations: PublicStation[];
  counties: string[];
  located_count: number;
}

export type ChatMode = "weather" | "history";

export type ChatOutcome = "success" | "history" | "needs_clarification" | "no_data";

export interface Source {
  station_id: string;
  station: string;
  county: string | null;
  kind: "observation" | "forecast";
  times: string[];
  measurements: string[];
}
export interface ResultMetadata {
  sources?: Source[];
  coverage?: "subset" | "complete" | null;
}

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
  metadata?: ResultMetadata;
  request_input?: { point?: RequestedPoint | null; station_id?: string | null; mode?: ChatMode | null };
}
export interface SavedConversation extends ConversationSummary {
  context: ConversationContext;
  messages: SavedMessage[];
  next_before: number | null;
}

export interface SavedChatResponse extends ChatResponse, ResultMetadata {
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
function isStationId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9]{1,20}$/.test(value);
}
export function isStationCatalog(value: unknown): value is StationCatalog {
  if (!isObject(value) || !Array.isArray(value.stations) || !Array.isArray(value.counties) ||
    !value.counties.every(county => typeof county === "string") || !Number.isInteger(value.located_count) ||
    Number(value.located_count) < 0 || Number(value.located_count) > value.stations.length) return false;
  return value.stations.every(station => isObject(station) && isStationId(station.id) &&
    typeof station.name === "string" && !!station.name.trim() && typeof station.county === "string" &&
    (station.distance_km === null || (typeof station.distance_km === "number" &&
      Number.isFinite(station.distance_km) && station.distance_km >= 0)) &&
    Object.keys(station).every(key => ["id", "name", "county", "distance_km"].includes(key))) &&
    new Set(value.stations.map(station => station.id)).size === value.stations.length;
}
function isOutcome(value: unknown): value is ChatOutcome {
  return typeof value === "string" && ["success", "history", "needs_clarification", "no_data"].includes(value);
}
function isSource(value: unknown): value is Source {
  return isObject(value) && typeof value.station_id === "string" && typeof value.station === "string" &&
    (value.county === null || typeof value.county === "string") &&
    (value.kind === "observation" || value.kind === "forecast") &&
    Array.isArray(value.times) && value.times.every((item) => typeof item === "string") &&
    Array.isArray(value.measurements) && value.measurements.every((item) => typeof item === "string");
}
function isMetadata(value: unknown): value is ResultMetadata | undefined {
  return value === undefined || (isObject(value) &&
    (value.sources === undefined || (Array.isArray(value.sources) && value.sources.every(isSource))) &&
    (value.coverage === undefined || value.coverage === null || value.coverage === "subset" || value.coverage === "complete"));
}
function isRequestInput(value: unknown): boolean {
  return (
    value === undefined ||
    (isObject(value) &&
      (value.point === undefined || value.point === null || isPoint(value.point)) &&
      (value.station_id === undefined || value.station_id === null || isStationId(value.station_id)) &&
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
    isMetadata(value.metadata) &&
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
    isMetadata(value) &&
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
