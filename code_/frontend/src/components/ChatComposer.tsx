import { useEffect, type FormEvent, type RefObject } from "react";
import Icon from "./Icon";

type Props = {
  draft: string;
  ready: boolean;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
};

export default function ChatComposer({ draft, ready, isSending, textareaRef, onDraftChange, onSubmit }: Props) {
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
          placeholder={isSending ? "Waiting for a response…" : "Ask about the weather…"}
          ref={textareaRef}
          maxLength={4000}
          rows={1}
          value={draft}
        />
        <div className="composer-toolbar">
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
        <span>For the best answer, choose a map point and include a date.</span>
        <span className="keyboard-hint">
          Enter to send <span>·</span> Shift + Enter for a new line
        </span>
      </div>
    </form>
  );
}
