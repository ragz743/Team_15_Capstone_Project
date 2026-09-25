import { useEffect, useRef, useState } from "react";
import { ApiError, sendChat, type ChatMessage as ApiChatMessage } from "./lib/api";
import ChatWorkspace from "./components/ChatWorkspace";

/**
 * A turn in the transcript. Carries an id and timestamp for rendering on top
 * of the {role, content} shape the backend expects. `pending` marks an
 * assistant bubble that is still streaming / waiting on the server.
 */
type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
  pending?: boolean;
  error?: boolean;
};


function createId() {
  return globalThis.crypto?.randomUUID() ?? Math.random().toString(36).slice(2, 10);
}

/**
 * Strip UI-only fields before sending transcript to the backend. The backend
 * chat schema only understands {role, content}.
 */
function toApiMessages(messages: Message[]): ApiChatMessage[] {
  return messages
    .filter((m) => !m.pending && !m.error)
    .map((m) => ({ role: m.role, content: m.text }));
}

export default function App() {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  // Single in-flight request guard — keeps the UI from pipelining user turns
  // while the assistant is still thinking.
  const [isSending, setIsSending] = useState(false);
  // Track the active request so we can abort it on unmount / clear.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = draft.trim();
    if (!text || abortRef.current) {
      return;
    }

    const userMessage: Message = {
      id: createId(),
      role: "user",
      text,
      timestamp: new Date().toISOString(),
    };
    const pendingAssistant: Message = {
      id: createId(),
      role: "assistant",
      text: "",
      timestamp: new Date().toISOString(),
      pending: true,
    };

    // Snapshot the transcript the backend will see so we aren't racing state updates.
    const historyForApi = toApiMessages([...messages, userMessage]);

    setMessages((previous) => [...previous, userMessage, pendingAssistant]);
    setDraft("");
    setIsSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { reply } = await sendChat(historyForApi, controller.signal);
      if (abortRef.current !== controller) {
        return;
      }
      setMessages((previous) =>
        previous.map((m) =>
          m.id === pendingAssistant.id
            ? { ...m, text: reply, pending: false, timestamp: new Date().toISOString() }
            : m,
        ),
      );
    } catch (err) {
      if (abortRef.current !== controller) {
        return;
      }
      if (err instanceof DOMException && err.name === "AbortError") {
        setMessages((previous) => previous.filter((m) => m.id !== pendingAssistant.id));
        return;
      }

      const detail =
        err instanceof ApiError
          ? err.detail ?? err.message
          : "Something went wrong reaching the AWN backend.";
      setMessages((previous) =>
        previous.map((m) =>
          m.id === pendingAssistant.id
            ? {
                ...m,
                text: detail,
                pending: false,
                error: true,
                timestamp: new Date().toISOString(),
              }
            : m,
        ),
      );
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setIsSending(false);
      }
    }
  }

  function handleClearConversation() {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setDraft("");
    setIsSending(false);
  }

  return (
    <ChatWorkspace
      messages={messages}
      draft={draft}
      isSending={isSending}
      onDraftChange={setDraft}
      onSubmit={handleSubmit}
      onNewConversation={handleClearConversation}
    />
  );
}
