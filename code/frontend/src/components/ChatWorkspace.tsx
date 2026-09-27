import { useEffect, useRef, useState, type FormEvent } from "react";
import Icon from "./Icon";
import WsuLogo from "./WsuLogo";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
  requestId?: string;
  pending?: boolean;
  error?: boolean;
  status?: "pending" | "completed" | "failed";
};

export type ConversationItem = {
  id: string;
  title: string;
  updated_at: string;
};

export type ConversationHistory = {
  conversations: ConversationItem[];
  selectedId: string | null;
  onSelect: (id: string) => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
  onLoadOlder?: () => void | Promise<void>;
  onLoadEarlier?: () => void | Promise<void>;
};

type ChatWorkspaceProps = {
  messages: ChatMessage[];
  draft: string;
  isSending: boolean;
  ready?: boolean;
  notice?: string;
  history?: ConversationHistory;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onNewConversation: () => void;
  onRetry?: (message: ChatMessage) => void;
};

const starters = [
  { icon: "thermometer", title: "Temperature", description: "Get a feel for local conditions", prompt: "What was the temperature in Pullman yesterday?" },
  { icon: "rain", title: "Rainfall", description: "See how much rain has fallen", prompt: "How much rain fell in Prosser over the last week?" },
  { icon: "wind", title: "Wind", description: "Take a closer look at the wind", prompt: "What was the wind speed in Yakima yesterday?" },
] as const;
function historyGroup(value: string) {
  const date = new Date(value);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (date >= today) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date >= yesterday) return "Yesterday";
  const week = new Date(today);
  week.setDate(week.getDate() - 7);
  return date >= week ? "Previous 7 days" : "Older conversations";
}
const timeFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });
function formatTime(value: string) { return timeFormatter.format(new Date(value)); }

export default function ChatWorkspace({
  messages, draft, isSending, ready = true, notice = "", history,
  onDraftChange, onSubmit, onNewConversation, onRetry,
}: ChatWorkspaceProps) {
  const [search, setSearch] = useState("");
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const mobileSidebarRef = useRef<HTMLDialogElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const transcriptRef = useRef<HTMLElement | null>(null);
  const previousScrollRef = useRef<{ height: number; top: number } | null>(null);
  const conversations = history?.conversations ?? [];
  const conversationId = history?.selectedId ?? null;
  const olderChats = Boolean(history?.onLoadOlder);
  const lastUser = messages.findLast(message => message.role === "user");

  useEffect(() => {
    const node = textareaRef.current;
    if (node) {
      node.style.height = "0px";
      node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
    }
  }, [draft]);

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    const previous = previousScrollRef.current;
    node.scrollTop = previous ? previous.top + node.scrollHeight - previous.height : messages.length ? node.scrollHeight : 0;
    previousScrollRef.current = null;
  }, [messages]);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 761px)");
    const closeMobileSidebar = () => { if (desktop.matches) mobileSidebarRef.current?.close(); };
    desktop.addEventListener("change", closeMobileSidebar);
    return () => desktop.removeEventListener("change", closeMobileSidebar);
  }, []);

  function handleClearConversation() {
    mobileSidebarRef.current?.close();
    previousScrollRef.current = null;
    setSearch("");
    onNewConversation();
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    previousScrollRef.current = null;
    void onSubmit(event);
  }

  function openConversation(id: string) {
    mobileSidebarRef.current?.close();
    previousScrollRef.current = null;
    return history?.onSelect(id);
  }

  function refreshList(older = false) {
    return older ? history?.onLoadOlder?.() : history?.onRefresh();
  }

  async function loadEarlier() {
    const node = transcriptRef.current;
    if (node) previousScrollRef.current = { height: node.scrollHeight, top: node.scrollTop };
    try {
      await history?.onLoadEarlier?.();
    } catch (error) {
      previousScrollRef.current = null;
      throw error;
    }
  }

  const visibleChats = conversations.filter(chat => chat.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const groups = new Map<string, ConversationItem[]>();
  for (const chat of visibleChats) {
    const group = historyGroup(chat.updated_at);
    groups.set(group, [...(groups.get(group) ?? []), chat]);
  }
  const activeTitle = conversations.find(chat => chat.id === conversationId)?.title ?? messages.find(message => message.role === "user")?.text ?? "Conversation";
  const sidebarContent = <>
    <div className="sidebar-brand">
      <div className="brand-mark"><WsuLogo /></div>
      <div><h1>AgWeatherNet</h1><p>Your weather assistant</p></div>
      <button className="icon-button mobile-close" type="button" aria-label="Close conversations" onClick={() => mobileSidebarRef.current?.close()}><Icon name="close" /></button>
    </div>
    <button className="new-chat-button" onClick={handleClearConversation} type="button">
      <Icon name="plus" /><span>New conversation</span>
    </button>
    {history && <>
    <label className="history-search">
      <Icon name="search" />
      <input type="search" aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={event => setSearch(event.target.value)} />
    </label>
    <div className="history-heading"><h2>Conversations</h2><button className="icon-button" type="button" aria-label="Refresh conversations" title="Refresh conversations" disabled={isSending || !ready} onClick={() => void refreshList()}><Icon name="refresh" /></button></div>
    <nav className="saved-chats" aria-label="Saved conversations">
      {!ready && <p className="history-empty" role="status">Loading conversations…</p>}
      {ready && !visibleChats.length && <div className="history-empty"><Icon name={search ? "search" : "chat"} /><p>{search ? "No matching conversations" : "A fresh start"}</p><span>{search ? (olderChats ? "Try another search, or load older chats below." : "Try a different word or phrase.") : "Your conversations will appear here after your first question."}</span></div>}
      {Array.from(groups, ([label, chats]) => <div className="history-group" key={label}>
        <h3>{label}</h3>
        {chats.map(chat => <button key={chat.id} className="saved-chat" type="button" title={chat.title} aria-current={chat.id === conversationId ? "true" : undefined} onClick={() => void openConversation(chat.id)}>
          <Icon name="chat" /><span>{chat.title}</span>
        </button>)}
      </div>)}
      {olderChats && <button className="text-button load-older" type="button" disabled={isSending || !ready} onClick={() => void refreshList(true)}>Load older conversations</button>}
    </nav>
    </>}
    <div className="sidebar-bottom">
      <div className="university"><span className="university-mark"><WsuLogo /></span><div><strong>Washington State University</strong><span>AgWeatherNet</span></div></div>
      {history && <p className="history-note">History is linked to this browser.<br />Clearing cookies removes access.</p>}
    </div>
  </>;

  return (
    <div className="page-shell">
      <div className={`app-shell${sidebarVisible ? "" : " app-shell--collapsed"}`}>
        <aside className="sidebar desktop-sidebar" aria-label="Conversation sidebar" hidden={!sidebarVisible}>{sidebarContent}</aside>
        <dialog className="mobile-sidebar" ref={mobileSidebarRef} aria-label="Conversations" onClick={event => { if (event.target === event.currentTarget) event.currentTarget.close(); }}>
          <div className="sidebar">{sidebarContent}</div>
        </dialog>
        <main className="workspace">
          <header className="workspace-header">
            <div className="workspace-heading">
              <button className="icon-button desktop-toggle" type="button" aria-label={sidebarVisible ? "Hide sidebar" : "Show sidebar"} title={sidebarVisible ? "Hide sidebar" : "Show sidebar"} aria-expanded={sidebarVisible} onClick={() => setSidebarVisible(value => !value)}><Icon name="panel" /></button>
              <button className="icon-button mobile-toggle" type="button" aria-label="Open conversations" onClick={() => mobileSidebarRef.current?.showModal()}><Icon name="panel" /></button>
              <h2 title={messages.length ? activeTitle : undefined}>{messages.length ? activeTitle : "Weather assistant"}</h2>
            </div>
            <div className="header-actions">
              {conversationId && <button className="icon-button" type="button" aria-label="Reload saved conversation" title="Reload saved conversation" disabled={isSending || !ready} onClick={() => void openConversation(conversationId)}><Icon name="refresh" /></button>}
            </div>
          </header>

          {notice && <div className="conversation-notice" role="alert"><Icon name="warning" /><p>{notice}</p>{history && <button className="text-button" type="button" disabled={isSending || !ready} onClick={() => void refreshList()}>Try again</button>}</div>}
          <section aria-label="Conversation area" className={`transcript${messages.length ? "" : " transcript--empty"}`} ref={transcriptRef}>
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="welcome-mark"><WsuLogo /></div>
                <h3>Hi, I am <span>AWN.</span></h3>
                <p className="welcome-description">Ask about conditions across Washington, past and present.</p>
                <div className="starter-grid">
                  {starters.map(starter => <button className="starter-card" key={starter.title} type="button" disabled={isSending || !ready} onClick={() => { onDraftChange(starter.prompt); textareaRef.current?.focus(); }}>
                    <Icon name={starter.icon} /><strong>{starter.title}</strong><span>{starter.description}</span><Icon name="chevron" className="starter-arrow" />
                  </button>)}
                </div>
                <p className="starter-hint">Choose a starting point, or ask your own question below.</p>
              </div>
            ) : (
              <div className="message-stack" role="log" aria-label="Messages" aria-live="polite">
                {history?.onLoadEarlier && <button className="text-button earlier-messages" type="button" disabled={isSending || !ready} onClick={() => void loadEarlier()}>Load earlier messages</button>}
                {messages.map(message => (
                  <article className={`message-row message-row--${message.role}${message.error ? " message-row--error" : ""}`} key={message.id}>
                    {message.role === "assistant" && <div className="assistant-avatar"><WsuLogo /></div>}
                    <div className="message-content">
                      {message.role === "assistant" && <span className="message-author">AgWeatherNet</span>}
                      <div className="message-bubble">
                        {message.pending ? <div className="message-pending" role="status"><span className="dot" /><span className="dot" /><span className="dot" /><span className="sr-only">Preparing your response</span></div> : <p>{message.text}</p>}
                      </div>
                      {!message.pending && <div className="message-meta"><time dateTime={message.timestamp}>{formatTime(message.timestamp)}</time>
                        {onRetry && message === lastUser && message.status !== "completed" && !isSending && <button className="text-button retry-button" type="button" onClick={() => onRetry(message)}><Icon name="refresh" />Retry message</button>}
                      </div>}
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
                disabled={isSending || !ready}
                onChange={event => onDraftChange(event.target.value)}
                onKeyDown={event => {
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
                <button className="send-button" aria-label={isSending ? "Waiting for response" : "Send message"} title="Send message" disabled={!draft.trim() || isSending || !ready} type="submit"><Icon name="arrow" /></button>
              </div>
            </div>
            <div className="composer-footnote"><span>For the best answer, include a location and date.</span><span className="keyboard-hint">Enter to send <span>·</span> Shift + Enter for a new line</span></div>
          </form>
        </main>
      </div>
    </div>
  );
}
