import { useEffect, useRef } from "react";
import { answerText, sourceLabel } from "../lib/answerPresentation";
import type { ResultMetadata } from "../lib/api";
import Icon from "./Icon";
import WsuLogo from "./WsuLogo";
import type { Message } from "../lib/conversationState";

const starters = [
  {
    icon: "thermometer",
    title: "Temperature",
    description: "Get a feel for local conditions",
    prompt: "What was the temperature at the selected station yesterday?",
  },
  {
    icon: "rain",
    title: "Rainfall",
    description: "See how much rain has fallen",
    prompt: "How much rain fell at the selected station over the last week?",
  },
  {
    icon: "wind",
    title: "Wind",
    description: "Take a closer look at the wind",
    prompt: "What was the wind speed at the selected station yesterday?",
  },
] as const;

const timeFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });
function formatTime(value: string) {
  return timeFormatter.format(new Date(value));
}

type Props = {
  messages: Message[];
  ready: boolean;
  isSending: boolean;
  onLoadEarlier?: () => void | Promise<void>;
  onStarter: (text: string) => void;
  onRetry?: (message: Message) => void;
};

function SourceDetails({ metadata }: { metadata?: ResultMetadata }) {
  if (!metadata?.sources?.length) return null;
  return (
    <details className="source-details">
      <summary>Sources and coverage</summary>
      <ul>{metadata.sources.map((source, index) => <li key={index}>{sourceLabel(source)}</li>)}</ul>
      {metadata.coverage === "subset" && <p>Retrieved records may not cover every station or day in the request.</p>}
    </details>
  );
}

export default function ChatTranscript({ messages, ready, isSending, onLoadEarlier, onStarter, onRetry }: Props) {
  const transcriptRef = useRef<HTMLElement | null>(null);
  const previousScrollRef = useRef<{ height: number; top: number; firstId: string | undefined } | null>(null);
  const lastUser = messages.findLast((message) => message.role === "user");
  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    const previous = previousScrollRef.current;
    const addedEarlier =
      previous && messages[0]?.id !== previous.firstId && messages.some((message) => message.id === previous.firstId);
    node.scrollTop = addedEarlier
      ? previous.top + node.scrollHeight - previous.height
      : messages.length
        ? node.scrollHeight
        : 0;
    previousScrollRef.current = null;
  }, [messages]);
  async function loadEarlier() {
    const node = transcriptRef.current;
    if (node) previousScrollRef.current = { height: node.scrollHeight, top: node.scrollTop, firstId: messages[0]?.id };
    await onLoadEarlier?.();
  }
  return (
    <section
      aria-label="Conversation area"
      className={`transcript${messages.length ? "" : " transcript--empty"}`}
      ref={transcriptRef}
    >
      {messages.length === 0 ? (
        <div className="empty-state">
          <div className="welcome-mark">
            <WsuLogo />
          </div>
          <h3>
            Hi, I am <span>AWN.</span>
          </h3>
          <p className="welcome-description">Ask about conditions across Washington, past and present.</p>
          <div className="starter-grid">
            {starters.map((starter) => (
              <button
                className="starter-card"
                key={starter.title}
                type="button"
                disabled={isSending || !ready}
                onClick={() => {
                  onStarter(starter.prompt);
                }}
              >
                <Icon name={starter.icon} />
                <strong>{starter.title}</strong>
                <span>{starter.description}</span>
                <Icon name="chevron" className="starter-arrow" />
              </button>
            ))}
          </div>
          <p className="starter-hint">Choose a starting point, or ask your own question below.</p>
        </div>
      ) : (
        <div className="message-stack" role="log" aria-label="Messages" aria-live="polite">
          {onLoadEarlier && (
            <button
              className="text-button earlier-messages"
              type="button"
              disabled={isSending || !ready}
              onClick={() => void loadEarlier()}
            >
              Load earlier messages
            </button>
          )}
          {messages.map((message) => (
            <article
              className={`message-row message-row--${message.role}${message.error ? " message-row--error" : ""}`}
              key={message.id}
            >
              {message.role === "assistant" && (
                <div className="assistant-avatar">
                  <WsuLogo />
                </div>
              )}
              <div className="message-content">
                {message.role === "assistant" && <span className="message-author">AgWeatherNet</span>}
                <div className="message-bubble">
                  {message.pending ? (
                    <div className="message-pending" role="status">
                      <span className="dot" />
                      <span className="dot" />
                      <span className="dot" />
                      <span className="sr-only">Preparing your response</span>
                    </div>
                  ) : (
                    <p>{message.role === "assistant" ? answerText(message.text, message.metadata?.sources) : message.text}</p>
                  )}
                </div>
                <SourceDetails metadata={message.metadata} />
                {!message.pending && (
                  <div className="message-meta">
                    <time dateTime={message.timestamp}>{formatTime(message.timestamp)}</time>
                    {onRetry && message === lastUser && message.status !== "completed" && !isSending && (
                      <button className="text-button retry-button" type="button" onClick={() => onRetry(message)}>
                        <Icon name="refresh" />
                        Retry message
                      </button>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
