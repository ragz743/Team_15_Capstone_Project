import {
  ApiError,
  type ConversationSummary,
  type ChatMode,
  type RequestedPoint,
  type ResultMetadata,
  type SavedChatResponse,
  type SavedConversation,
} from "./api.ts";

export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
  requestId?: string;
  mode?: ChatMode;
  metadata?: ResultMetadata;
  point?: RequestedPoint | null;
  pending?: boolean;
  error?: boolean;
  status?: "pending" | "completed" | "failed";
};

export type ConversationState = {
  draft: string;
  mode: ChatMode;
  messages: Message[];
  conversations: ConversationSummary[];
  conversationId: string | null;
  point: RequestedPoint | null;
  pendingPoint: RequestedPoint | null;
  busy: boolean;
  ready: boolean;
  notice: string;
  nextBefore: number | null;
  hasOlder: boolean;
};

export const initialState: ConversationState = {
  draft: "",
  mode: "weather",
  messages: [],
  conversations: [],
  conversationId: null,
  point: null,
  pendingPoint: null,
  busy: false,
  ready: false,
  notice: "",
  nextBefore: null,
  hasOlder: false,
};

export type ConversationAction =
  | { type: "draft"; value: string }
  | { type: "mode"; value: ChatMode }
  | { type: "point"; value: RequestedPoint }
  | { type: "loading" }
  | { type: "finished" }
  | { type: "notice"; value: string }
  | { type: "new" }
  | { type: "list"; items: ConversationSummary[]; older?: boolean }
  | { type: "created"; chat: ConversationSummary }
  | { type: "loaded"; chat: SavedConversation; older?: boolean; draft?: string }
  | { type: "sending"; message: Message }
  | { type: "answered"; result: SavedChatResponse; text: string }
  | { type: "failed"; requestId: string; error: string };

function savedMessages(chat: SavedConversation): Message[] {
  return chat.messages.map((message) => ({
    id: message.id,
    role: message.role,
    text: message.content,
    timestamp: message.created_at,
    requestId: message.request_id,
    status: message.status,
    metadata: message.metadata,
    point: message.request_input?.point ?? null,
    mode: message.request_input?.mode ?? "weather",
  }));
}

function loadChat(
  state: ConversationState,
  action: Extract<ConversationAction, { type: "loaded" }>,
): ConversationState {
  const messages = savedMessages(action.chat);
  if (action.older)
    return { ...state, messages: [...messages, ...state.messages], nextBefore: action.chat.next_before };
  const lastUser = messages.findLast((message) => message.role === "user");
  const pendingPoint = lastUser?.status !== "completed" ? (lastUser?.point ?? null) : null;
  return {
    ...state,
    messages,
    conversationId: action.chat.id,
    nextBefore: action.chat.next_before,
    point: pendingPoint ?? action.chat.context.point ?? null,
    pendingPoint,
    mode: lastUser?.status !== "completed" ? (lastUser?.mode ?? "weather") : "weather",
    draft: action.draft ?? "",
    notice: "",
  };
}

function pendingMessages(messages: Message[], message: Message): Message[] {
  const retained = messages.filter((item) => item.requestId !== message.requestId);
  return [
    ...retained,
    { ...message, status: "pending" },
    {
      id: `${message.requestId}:assistant`,
      requestId: message.requestId,
      role: "assistant",
      text: "",
      timestamp: message.timestamp,
      pending: true,
    },
  ];
}

function samePoint(left: RequestedPoint | null, right: RequestedPoint | null): boolean {
  return left?.latitude === right?.latitude && left?.longitude === right?.longitude;
}

function answered(state: ConversationState, result: SavedChatResponse, text: string): ConversationState {
  const savedPoint = result.context.point ?? null;
  const pendingPoint = samePoint(state.pendingPoint, savedPoint) ? null : state.pendingPoint;
  const messages = state.messages.map((message) =>
    message.requestId !== result.request_id
      ? message
      : {
          ...message,
          status: "completed" as const,
          pending: false,
          error: false,
          ...(message.role === "assistant" ? { text: result.reply, timestamp: new Date().toISOString(),
              metadata: { sources: result.sources, coverage: result.coverage } } : {}),
        },
  );
  return {
    ...state,
    messages,
    point: pendingPoint ?? savedPoint,
    pendingPoint,
    draft: state.draft.trim() === text ? "" : state.draft,
  };
}

export function conversationReducer(state: ConversationState, action: ConversationAction): ConversationState {
  switch (action.type) {
    case "draft":
      return { ...state, draft: action.value };
    case "mode":
      return { ...state, mode: action.value };
    case "point":
      return { ...state, point: action.value, pendingPoint: action.value };
    case "loading":
      return { ...state, busy: true, notice: "" };
    case "finished":
      return { ...state, busy: false, ready: true };
    case "notice":
      return { ...state, notice: action.value };
    case "new":
      return { ...initialState, conversations: state.conversations, hasOlder: state.hasOlder, ready: true };
    case "created":
      return { ...state, conversationId: action.chat.id, conversations: [action.chat, ...state.conversations] };
    case "loaded":
      return loadChat(state, action);
    case "list":
      return {
        ...state,
        hasOlder: action.items.length === 50,
        conversations: action.older
          ? [...new Map([...state.conversations, ...action.items].map((chat) => [chat.id, chat])).values()]
          : action.items,
      };
    case "sending":
      return { ...state, busy: true, notice: "", messages: pendingMessages(state.messages, action.message) };
    case "answered":
      return answered(state, action.result, action.text);
    case "failed":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.requestId !== action.requestId
            ? message
            : {
                ...message,
                status: "failed",
                pending: false,
                ...(message.role === "assistant" ? { text: action.error, error: true } : {}),
              },
        ),
      };
  }
}

const selectionKey = "awn.selectedConversation";
export function selectedConversation(): string | null {
  try {
    return sessionStorage.getItem(selectionKey);
  } catch {
    return null;
  }
}
export function rememberSelection(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(selectionKey, id);
    else sessionStorage.removeItem(selectionKey);
  } catch {
    /* Server persistence remains available without browser storage. */
  }
}
export function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? (error.detail ?? error.message)
    : "Could not load the conversation. Please try again.";
}
