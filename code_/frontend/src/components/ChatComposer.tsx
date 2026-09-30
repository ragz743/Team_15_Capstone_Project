import { useEffect, type FormEvent, type RefObject } from "react";
import type { ChatMode } from "../lib/api";
import Icon from "./Icon";

type Props = {
  draft: string;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  ready: boolean;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
};

export default function ChatComposer({ draft, mode, onModeChange, ready, isSending, textareaRef, onDraftChange, onSubmit }: Props) {
  useEffect(() => {
    const node = textareaRef.current;
    if (node) {
      node.style.height = "0px";
      node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
    }
  }, [draft, textareaRef]);
  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className="composer-shell">
        <textarea
          aria-label="Type your message"
          className="composer-input"
          disabled={isSending || !ready}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder={isSending ? "Waiting for a response…" : mode === "history" ? "Find a past conversation…" : "Ask about the weather…"}
          ref={textareaRef}
          maxLength={4000}
          rows={1}
          value={draft}
        />
        <div className="composer-toolbar">
          <label className="chat-mode">
            Ask about
            <select aria-label="Question type" value={mode} disabled={isSending || !ready}
              onChange={(event) => onModeChange(event.target.value as ChatMode)}>
              <option value="weather">Weather</option>
              <option value="history">Past conversations</option>
            </select>
          </label>
          <button
            className="send-button"
            aria-label={isSending ? "Waiting for response" : "Send message"}
            title="Send message"
            disabled={!draft.trim() || isSending || !ready}
            type="submit"
          >
            <Icon name="arrow" />
          </button>
        </div>
      </div>
      <div className="composer-footnote">
        <span>{mode === "history" ? "Search conversations saved in this browser." : "For the best answer, choose a map point and include a date."}</span>
        <span className="keyboard-hint">
          Enter to send <span>·</span> Shift + Enter for a new line
        </span>
      </div>
    </form>
  );
}
