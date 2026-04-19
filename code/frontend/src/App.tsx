import { useEffect, useRef, useState } from "react";
import { ApiError, sendChat, type ChatMessage as ApiChatMessage } from "./lib/api";

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

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

function formatTime(value: string) {
  return timeFormatter.format(new Date(value));
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const transcriptRef = useRef<HTMLElement | null>(null);
  // Track the active request so we can abort it on unmount / clear.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) {
      return;
    }
    node.style.height = "0px";
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
  }, [draft]);

  useEffect(() => {
    const node = transcriptRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = draft.trim();
    if (!text || isSending) {
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
      setMessages((previous) =>
        previous.map((m) =>
          m.id === pendingAssistant.id
            ? { ...m, text: reply, pending: false, timestamp: new Date().toISOString() }
            : m,
        ),
      );
    } catch (err) {
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
      }
      setIsSending(false);
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
    <div className="page-shell">
      <div className="app-shell">
        <aside className="sidebar">
          <div className="sidebar-top">
            <div className="brand-mark">AW</div>
            <p className="eyebrow">Mock Prototype</p>
            <h1>AG Weather Net Assistant</h1>
          </div>

          <div className="sidebar-bottom">
            <button className="ghost-link" onClick={handleClearConversation} type="button">
              Clear conversation
            </button>
          </div>
        </aside>

        <main className="workspace">
          <header className="workspace-header">
            <div>
              <p className="eyebrow">Conversation</p>
              <h2>Hi, I am AWN.</h2>
            </div>
          </header>

          <section
            aria-label="Conversation area"
            className="transcript"
            ref={transcriptRef}
          >
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-line" />
                <h3>No conversation yet, ask a question to get started</h3>
              </div>
            ) : (
              <div className="message-stack">
                {messages.map((message) => (
                  <article
                    className={`message-row message-row--${message.role}${
                      message.error ? " message-row--error" : ""
                    }`}
                    key={message.id}
                  >
                    <div className="message-bubble">
                      {message.pending ? (
                        <p className="message-pending">
                          <span className="dot" />
                          <span className="dot" />
                          <span className="dot" />
                        </p>
                      ) : (
                        <p>{message.text}</p>
                      )}
                      <time>{formatTime(message.timestamp)}</time>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <form className="composer" onSubmit={handleSubmit}>
            <div className="composer-shell">
              <textarea
                aria-label="Type your message"
                className="composer-input"
                disabled={isSending}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    const form = event.currentTarget.form;
                    if (form) {
                      form.requestSubmit();
                    }
                  }
                }}
                placeholder={
                  isSending ? "Waiting for a response…" : "Type your question here"
                }
                ref={textareaRef}
                rows={1}
                value={draft}
              />

              <button
                className="send-button"
                disabled={!draft.trim() || isSending}
                type="submit"
              >
                {isSending ? "Sending…" : "Send"}
              </button>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}
