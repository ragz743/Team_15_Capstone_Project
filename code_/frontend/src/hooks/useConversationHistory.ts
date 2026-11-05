import { useEffect, useRef, type Dispatch } from "react";
import { ApiError, listConversations, loadConversation } from "../lib/api";
import {
  errorMessage,
  rememberSelection,
  selectedConversation,
  type ConversationAction,
  type ConversationState,
} from "../lib/conversationState";
import { RequestScope } from "../lib/requestScope";

async function restore(dispatch: Dispatch<ConversationAction>, scope: RequestScope, controller: AbortController) {
  try {
    const items = await listConversations(controller.signal);
    if (!scope.owns(controller)) return;
    dispatch({ type: "list", items });
    const id = selectedConversation();
    if (id) {
      const chat = await loadConversation(id, controller.signal);
      if (scope.owns(controller)) dispatch({ type: "loaded", chat });
    }
  } catch (error) {
    if (!scope.owns(controller)) return;
    if (error instanceof ApiError && error.status === 404) rememberSelection(null);
    else dispatch({ type: "notice", value: errorMessage(error) });
  } finally {
    if (scope.finish(controller)) dispatch({ type: "finished" });
  }
}

export function useConversationHistory(
  state: ConversationState,
  dispatch: Dispatch<ConversationAction>,
  scope: RequestScope,
) {
  const drafts = useRef(new Map<string, string>());
  useEffect(() => {
    const controller = scope.begin();
    void restore(dispatch, scope, controller);
    return () => scope.cancel();
  }, [dispatch, scope]);

  async function open(id: string, before?: number) {
    if (!before) drafts.current.set(state.conversationId ?? "new", state.draft);
    const controller = scope.begin();
    dispatch({ type: "loading" });
    try {
      const chat = await loadConversation(id, controller.signal, before);
      if (!scope.owns(controller)) return;
      dispatch({ type: "loaded", chat, older: !!before, draft: drafts.current.get(id) });
      rememberSelection(id);
    } catch (error) {
      if (scope.owns(controller)) dispatch({ type: "notice", value: errorMessage(error) });
    } finally {
      if (scope.finish(controller)) dispatch({ type: "finished" });
    }
  }

  async function refresh(older = false) {
    const controller = scope.begin();
    dispatch({ type: "loading" });
    try {
      const items = await listConversations(controller.signal, older ? state.conversations.at(-1) : undefined);
      if (scope.owns(controller)) dispatch({ type: "list", items, older });
    } catch (error) {
      if (scope.owns(controller)) dispatch({ type: "notice", value: errorMessage(error) });
    } finally {
      if (scope.finish(controller)) dispatch({ type: "finished" });
    }
  }

  function clear() {
    drafts.current.set(state.conversationId ?? "new", state.draft);
    scope.cancel();
    rememberSelection(null);
    dispatch({ type: "new" });
  }
  return { open, refresh, clear };
}
