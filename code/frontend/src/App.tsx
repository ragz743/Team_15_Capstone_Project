import { useEffect, useRef, useState } from "react";
import { ApiError, createConversation, listConversations, loadConversation, sendSavedChat,
  type ConversationSummary, type SavedMessage } from "./lib/api";
import { RequestScope } from "./lib/requestScope";
import ChatWorkspace, { type ChatMessage as Message } from "./components/ChatWorkspace";

const selectionKey = "awn.selectedConversation";
function fromSaved(messages: SavedMessage[]): Message[] {
  return messages.map(m => ({ id: m.id, role: m.role, text: m.content, timestamp: m.created_at,
    requestId: m.request_id, status: m.status }));
}
function rememberSelection(id: string | null) {
  try {
    if (id) sessionStorage.setItem(selectionKey, id);
    else sessionStorage.removeItem(selectionKey);
  } catch { /* Storage may be disabled; the server still saves the conversation. */ }
}
function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.detail ?? error.message : "Could not load the conversation. Please try again.";
}

export default function App() {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState("");
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [olderChats, setOlderChats] = useState(false);
  const requests = useRef(new RequestScope());
  const drafts = useRef(new Map<string, string>());
  useEffect(() => {
    const scope = requests.current;
    const controller = scope.begin();
    async function restore() {
      try {
        const saved = await listConversations(controller.signal);
        if (!scope.owns(controller)) return;
        setConversations(saved);
        setOlderChats(saved.length === 50);
        let selected: string | null = null;
        try { selected = sessionStorage.getItem(selectionKey); } catch { /* Selection is optional. */ }
        if (selected) {
          try {
            const chat = await loadConversation(selected, controller.signal);
            if (!scope.owns(controller)) return;
            setConversationId(chat.id);
            setMessages(fromSaved(chat.messages));
            setNextBefore(chat.next_before);
          } catch (err) {
            if (err instanceof ApiError && err.status === 404) rememberSelection(null);
            else throw err;
          }
        }
      } catch (err) {
        if (scope.owns(controller)) setNotice(errorMessage(err));
      } finally {
        if (scope.finish(controller)) setReady(true);
      }
    }
    void restore();
    return () => { scope.cancel(); };
  }, []);

  async function openConversation(id: string, before?: number) {
    if (!before) {
      setReady(false);
      drafts.current.set(conversationId ?? "new", draft);
    }
    const scope = requests.current;
    const controller = scope.begin();
    setIsSending(true);
    setNotice("");
    try {
      const chat = await loadConversation(id, controller.signal, before);
      if (!scope.owns(controller)) return;
      setMessages(previous => before ? [...fromSaved(chat.messages), ...previous] : fromSaved(chat.messages));
      setConversationId(id);
      rememberSelection(id);
      setNextBefore(chat.next_before);
      if (!before) {
        setDraft(drafts.current.get(id) ?? "");
      }
    } catch (err) {
      if (scope.owns(controller)) setNotice(errorMessage(err));
    } finally {
      if (scope.finish(controller)) { setIsSending(false); setReady(true); }
    }
  }

  async function refreshList(older = false) {
    const scope = requests.current;
    const controller = scope.begin();
    setIsSending(true);
    try {
      const before = older ? conversations.at(-1) : undefined;
      const saved = await listConversations(controller.signal, before);
      if (!scope.owns(controller)) return;
      setConversations(previous => older ? [...previous, ...saved] : saved);
      setOlderChats(saved.length === 50);
      setNotice("");
      setReady(true);
    } catch (err) {
      if (scope.owns(controller)) setNotice(errorMessage(err));
    } finally {
      if (scope.finish(controller)) setIsSending(false);
    }
  }

  async function submitTurn(text: string, retryId?: string) {
    if (!text.trim() || !ready || requests.current.active) return;
    const requestId = retryId ?? crypto.randomUUID();
    const userMessage: Message = { id: `${requestId}:user`, role: "user", text,
      timestamp: new Date().toISOString(), requestId, status: "pending" };
    const pendingAssistant: Message = { id: `${requestId}:assistant`, role: "assistant", text: "",
      timestamp: new Date().toISOString(), pending: true, requestId };
    setMessages(previous => retryId
      ? [...previous.filter(m => m.id !== pendingAssistant.id), pendingAssistant]
      : [...previous, userMessage, pendingAssistant]);
    setIsSending(true);
    setNotice("");
    const scope = requests.current;
    const controller = scope.begin();
    try {
      let id = conversationId;
      if (!id) {
        const created = await createConversation(controller.signal);
        if (!scope.owns(controller)) return;
        id = created.id;
        setConversationId(id);
        rememberSelection(id);
        setConversations(previous => [created, ...previous]);
      }
      const result = await sendSavedChat(id, requestId, text, controller.signal);
      if (!scope.owns(controller)) return;
      setMessages(previous => previous.map(m => m.id === pendingAssistant.id
        ? { ...m, text: result.reply, pending: false, error: false, status: "completed", timestamp: new Date().toISOString() }
        : m.requestId === requestId ? { ...m, status: "completed" } : m));
      setDraft(current => current.trim() === text ? "" : current);
      try {
        const saved = await listConversations(controller.signal);
        if (scope.owns(controller)) { setConversations(saved); setOlderChats(saved.length === 50); }
      } catch (err) {
        if (scope.owns(controller)) setNotice(errorMessage(err));
      }
    } catch (err) {
      if (!scope.owns(controller)) return;
      if (err instanceof DOMException && err.name === "AbortError") return;
      setMessages(previous => previous.map(m => m.id === pendingAssistant.id
        ? { ...m, text: errorMessage(err), pending: false, error: true }
        : m.requestId === requestId ? { ...m, status: "failed" } : m));
    } finally {
      if (scope.finish(controller)) setIsSending(false);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitTurn(draft.trim());
  }
  function handleClearConversation() {
    drafts.current.set(conversationId ?? "new", draft);
    requests.current.cancel();
    setReady(true);
    setConversationId(null);
    rememberSelection(null);
    setMessages([]);
    setNextBefore(null);
    setDraft("");
    setNotice("");
    setIsSending(false);
  }
  return (
    <ChatWorkspace
      messages={messages}
      draft={draft}
      isSending={isSending}
      ready={ready}
      notice={notice}
      history={{
        conversations,
        selectedId: conversationId,
        onSelect: openConversation,
        onRefresh: () => refreshList(),
        onLoadOlder: olderChats ? () => refreshList(true) : undefined,
        onLoadEarlier: conversationId && nextBefore
          ? () => openConversation(conversationId, nextBefore) : undefined,
      }}
      onDraftChange={setDraft}
      onSubmit={handleSubmit}
      onNewConversation={handleClearConversation}
      onRetry={message => void submitTurn(message.text, message.requestId)}
    />
  );
}
