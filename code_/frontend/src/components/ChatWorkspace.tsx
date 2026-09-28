import { useEffect, useRef, useState, type FormEvent } from "react";
import ChatComposer from "./ChatComposer";
import ChatTranscript from "./ChatTranscript";
import ConversationSidebar from "./ConversationSidebar";
import LocationPicker from "./LocationPicker";
import Icon from "./Icon";
import type { RequestedPoint } from "../lib/api";
import type { Message } from "../lib/conversationState";
import type { ConversationHistory } from "./chatTypes";

export type { Message as ChatMessage } from "../lib/conversationState";

type ChatWorkspaceProps = {
  messages: Message[];
  draft: string;
  point: RequestedPoint | null;
  onPointChange: (point: RequestedPoint) => void;
  isSending: boolean;
  ready?: boolean;
  notice?: string;
  history?: ConversationHistory;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onNewConversation: () => void;
  onRetry?: (message: Message) => void;
};

export default function ChatWorkspace({
  messages,
  draft,
  isSending,
  ready = true,
  notice = "",
  history,
  point,
  onPointChange,
  onDraftChange,
  onSubmit,
  onNewConversation,
  onRetry,
}: ChatWorkspaceProps) {
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const mobileSidebarRef = useRef<HTMLDialogElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const conversationId = history?.selectedId ?? null;
  const activeTitle =
    history?.conversations.find((chat) => chat.id === conversationId)?.title ??
    messages.find((message) => message.role === "user")?.text ??
    "Conversation";
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 761px)");
    const closeMobileSidebar = () => {
      if (desktop.matches) mobileSidebarRef.current?.close();
    };
    desktop.addEventListener("change", closeMobileSidebar);
    return () => desktop.removeEventListener("change", closeMobileSidebar);
  }, []);
  function newConversation() {
    mobileSidebarRef.current?.close();
    onNewConversation();
    requestAnimationFrame(() => textareaRef.current?.focus());
  }
  function openConversation(id: string) {
    mobileSidebarRef.current?.close();
    return history?.onSelect(id);
  }
  const sidebarContent = (
    <ConversationSidebar
      history={history ? { ...history, onSelect: openConversation } : undefined}
      ready={ready}
      isSending={isSending}
      onNewConversation={newConversation}
      onClose={() => mobileSidebarRef.current?.close()}
    />
  );
  return (
    <div className="page-shell">
      <div className={`app-shell${sidebarVisible ? "" : " app-shell--collapsed"}`}>
        <aside className="sidebar desktop-sidebar" aria-label="Conversation sidebar" hidden={!sidebarVisible}>
          {sidebarContent}
        </aside>
        <dialog
          className="mobile-sidebar"
          ref={mobileSidebarRef}
          aria-label="Conversations"
          onClick={(event) => {
            if (event.target === event.currentTarget) event.currentTarget.close();
          }}
        >
          <div className="sidebar">{sidebarContent}</div>
        </dialog>
        <main className="workspace">
          <header className="workspace-header">
            <div className="workspace-heading">
              <button
                className="icon-button desktop-toggle"
                type="button"
                aria-label={sidebarVisible ? "Hide sidebar" : "Show sidebar"}
                title={sidebarVisible ? "Hide sidebar" : "Show sidebar"}
                aria-expanded={sidebarVisible}
                onClick={() => setSidebarVisible((value) => !value)}
              >
                <Icon name="panel" />
              </button>
              <button
                className="icon-button mobile-toggle"
                type="button"
                aria-label="Open conversations"
                onClick={() => mobileSidebarRef.current?.showModal()}
              >
                <Icon name="panel" />
              </button>
              <h2 title={messages.length ? activeTitle : undefined}>
                {messages.length ? activeTitle : "Weather assistant"}
              </h2>
            </div>
            <div className="header-actions">
              {conversationId && (
                <button
                  className="icon-button"
                  type="button"
                  aria-label="Reload saved conversation"
                  title="Reload saved conversation"
                  disabled={isSending || !ready}
                  onClick={() => void openConversation(conversationId)}
                >
                  <Icon name="refresh" />
                </button>
              )}
            </div>
          </header>

          {notice && (
            <div className="conversation-notice" role="alert">
              <Icon name="warning" />
              <p>{notice}</p>
              {history && (
                <button
                  className="text-button"
                  type="button"
                  disabled={isSending || !ready}
                  onClick={() => void history?.onRefresh()}
                >
                  Try again
                </button>
              )}
            </div>
          )}
          <details className="map-panel" open={!point && messages.length === 0}>
            <summary>{point ? "Change map point" : "Choose a map point"}</summary>
            <LocationPicker point={point} disabled={isSending || !ready} onChange={onPointChange} />
          </details>
          <ChatTranscript
            key={conversationId ?? "new"}
            messages={messages}
            isSending={isSending}
            ready={ready}
            onLoadEarlier={history?.onLoadEarlier}
            onRetry={onRetry}
            onStarter={(text) => {
              onDraftChange(text);
              textareaRef.current?.focus();
            }}
          />
          <ChatComposer
            draft={draft}
            isSending={isSending}
            ready={ready}
            textareaRef={textareaRef}
            onDraftChange={onDraftChange}
            onSubmit={onSubmit}
          />
        </main>
      </div>
    </div>
  );
}
