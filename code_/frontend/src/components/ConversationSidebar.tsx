import { useState } from "react";
import Icon from "./Icon";
import WsuLogo from "./WsuLogo";
import type { ConversationHistory, ConversationItem } from "./chatTypes";

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

type Props = {
  history?: ConversationHistory;
  ready: boolean;
  isSending: boolean;
  onNewConversation: () => void;
  onClose: () => void;
};

export default function ConversationSidebar({ history, ready, isSending, onNewConversation, onClose }: Props) {
  const [search, setSearch] = useState("");
  const conversations = history?.conversations ?? [];
  const conversationId = history?.selectedId ?? null;
  const olderChats = Boolean(history?.onLoadOlder);
  const visibleChats = conversations.filter((chat) =>
    chat.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  const groups = new Map<string, ConversationItem[]>();
  for (const chat of visibleChats) {
    const label = historyGroup(chat.updated_at);
    groups.set(label, [...(groups.get(label) ?? []), chat]);
  }
  function newConversation() {
    setSearch("");
    onNewConversation();
  }
  return (
    <>
      <div className="sidebar-brand">
        <div className="brand-mark">
          <WsuLogo />
        </div>
        <div>
          <h1>AgWeatherNet</h1>
          <p>Your weather assistant</p>
        </div>
        <button
          className="icon-button mobile-close"
          type="button"
          aria-label="Close conversations"
          onClick={() => onClose()}
        >
          <Icon name="close" />
        </button>
      </div>
      <button className="new-chat-button" onClick={newConversation} type="button">
        <Icon name="plus" />
        <span>New conversation</span>
      </button>
      {history && (
        <>
          <label className="history-search">
            <Icon name="search" />
            <input
              type="search"
              aria-label="Search conversations"
              placeholder="Search conversations"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <div className="history-heading">
            <h2>Conversations</h2>
            <button
              className="icon-button"
              type="button"
              aria-label="Refresh conversations"
              title="Refresh conversations"
              disabled={isSending || !ready}
              onClick={() => void history?.onRefresh()}
            >
              <Icon name="refresh" />
            </button>
          </div>
          <nav className="saved-chats" aria-label="Saved conversations">
            {!ready && (
              <p className="history-empty" role="status">
                Loading conversations…
              </p>
            )}
            {ready && !visibleChats.length && (
              <div className="history-empty">
                <Icon name={search ? "search" : "chat"} />
                <p>{search ? "No matching conversations" : "A fresh start"}</p>
                <span>
                  {search
                    ? olderChats
                      ? "Try another search, or load older chats below."
                      : "Try a different word or phrase."
                    : "Your conversations will appear here after your first question."}
                </span>
              </div>
            )}
            {Array.from(groups, ([label, chats]) => (
              <div className="history-group" key={label}>
                <h3>{label}</h3>
                {chats.map((chat) => (
                  <button
                    key={chat.id}
                    className="saved-chat"
                    type="button"
                    title={chat.title}
                    aria-current={chat.id === conversationId ? "true" : undefined}
                    onClick={() => void history?.onSelect(chat.id)}
                  >
                    <Icon name="chat" />
                    <span>{chat.title}</span>
                  </button>
                ))}
              </div>
            ))}
            {olderChats && (
              <button
                className="text-button load-older"
                type="button"
                disabled={isSending || !ready}
                onClick={() => void history?.onLoadOlder?.()}
              >
                Load older conversations
              </button>
            )}
          </nav>
        </>
      )}
      <div className="sidebar-bottom">
        <div className="university">
          <span className="university-mark">
            <WsuLogo />
          </span>
          <div>
            <strong>Washington State University</strong>
            <span>AgWeatherNet</span>
          </div>
        </div>
        {history && (
          <p className="history-note">
            History is linked to this browser.
            <br />
            Clearing cookies removes access.
          </p>
        )}
      </div>
    </>
  );
}
