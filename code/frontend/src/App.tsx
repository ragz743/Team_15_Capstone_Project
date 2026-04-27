import { useEffect, useRef, useState } from "react";

type UserMessage = {
  id: string;
  text: string;
  timestamp: string;
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


export default function App() {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<UserMessage[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const node = textareaRef.current;

    if (!node) {
      return;
    }

    node.style.height = "0px";
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
  }, [draft]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = draft.trim();
    if (!text) {
      return;
    }

    setMessages((previous) => [
      ...previous,
      {
        id: createId(),
        text,
        timestamp: new Date().toISOString(),
      },
    ]);
    setDraft("");
  }

  function handleClearConversation() {
    setMessages([]);
    setDraft("");
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

          <section aria-label="Conversation area" className="transcript">
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-line" />
                <h3>No conversation yet</h3>
                <p>
                  Assistant responses
                  will appear here once backend wiring is completed.
                </p>
              </div>
            ) : (
              <div className="message-stack">
                <p className="transcript-label">Your messages</p>

                {messages.map((message) => (
                  <article className="message-row" key={message.id}>
                    <div className="message-bubble">
                      <p>{message.text}</p>
                      <time>{formatTime(message.timestamp)}</time>
                    </div>
                  </article>
                ))}

                <p className="integration-note">
                  Assistant response space is reserved for backend integration.
                </p>
              </div>
            )}
          </section>

          <form className="composer" onSubmit={handleSubmit}>
            <div className="composer-shell">
              <textarea
                aria-label="Type your message"
                className="composer-input"
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
                placeholder="Type your question here"
                ref={textareaRef}
                rows={1}
                value={draft}
              />

              <button className="send-button" disabled={!draft.trim()} type="submit">
                Send
              </button>
            </div>

          </form>
        </main>
      </div>
    </div>
  );
}
