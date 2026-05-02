export type StoredChatRole = "user" | "assistant";

export interface StoredChatMessage {
  id: string;
  role: StoredChatRole;
  text: string;
  timestamp: string;
  error?: boolean;
}

export interface StoredConversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: StoredChatMessage[];
}

const STORAGE_KEY = "awn.chatHistory.v1";
const MAX_CONVERSATIONS = 12;
const UNTITLED_CONVERSATION = "New conversation";

function isBrowserStorageAvailable() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function getFirstUserMessage(messages: StoredChatMessage[]) {
  return messages.find((message) => message.role === "user" && message.text.trim());
}

export function buildConversationTitle(messages: StoredChatMessage[]) {
  const firstUserMessage = getFirstUserMessage(messages);
  if (!firstUserMessage) {
    return UNTITLED_CONVERSATION;
  }

  const normalized = firstUserMessage.text.trim().replace(/\s+/g, " ");
  return normalized.length > 56 ? `${normalized.slice(0, 53)}...` : normalized;
}

function parseConversations(value: string | null): StoredConversation[] {
  if (!value) {
    return [];
  }

  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter((conversation): conversation is StoredConversation => {
      return (
        typeof conversation === "object" &&
        conversation !== null &&
        "id" in conversation &&
        "messages" in conversation &&
        typeof conversation.id === "string" &&
        Array.isArray(conversation.messages)
      );
    });
  } catch {
    return [];
  }
}

export function loadConversations(): StoredConversation[] {
  if (!isBrowserStorageAvailable()) {
    return [];
  }

  return parseConversations(window.localStorage.getItem(STORAGE_KEY));
}

export function saveConversations(conversations: StoredConversation[]) {
  if (!isBrowserStorageAvailable()) {
    return;
  }

  const sorted = [...conversations]
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    .slice(0, MAX_CONVERSATIONS);

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sorted));
}
