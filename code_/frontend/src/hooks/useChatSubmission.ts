import type { Dispatch } from "react";
import { createConversation, listConversations, sendSavedChat } from "../lib/api";
import {
  errorMessage,
  rememberSelection,
  type ConversationAction,
  type ConversationState,
  type Message,
} from "../lib/conversationState";
import { RequestScope } from "../lib/requestScope";

async function refreshAfterAnswer(
  dispatch: Dispatch<ConversationAction>,
  scope: RequestScope,
  controller: AbortController,
) {
  try {
    const items = await listConversations(controller.signal);
    if (scope.owns(controller)) dispatch({ type: "list", items });
  } catch (error) {
    if (scope.owns(controller)) dispatch({ type: "notice", value: errorMessage(error) });
  }
}

export function useChatSubmission(
  state: ConversationState,
  dispatch: Dispatch<ConversationAction>,
  scope: RequestScope,
) {
  async function submit(retry?: Message) {
    const text = retry?.text ?? state.draft.trim();
    if (!text || !state.ready || scope.active) return;
    const requestId = retry?.requestId ?? crypto.randomUUID();
    const mode = retry ? (retry.mode ?? "weather") : state.mode;
    const point = retry ? (retry.point ?? null) : state.pendingPoint;
    const message: Message = {
      id: `${requestId}:user`,
      role: "user",
      text,
      requestId,
      point,
      mode,
      timestamp: retry?.timestamp ?? new Date().toISOString(),
    };
    const controller = scope.begin();
    dispatch({ type: "sending", message });
    try {
      let id = state.conversationId;
      if (!id) {
        const chat = await createConversation(controller.signal);
        if (!scope.owns(controller)) return;
        id = chat.id;
        rememberSelection(id);
        dispatch({ type: "created", chat });
      }
      const result = await sendSavedChat(id, requestId, text, controller.signal, point, mode);
      if (!scope.owns(controller)) return;
      dispatch({ type: "answered", result, text });
      await refreshAfterAnswer(dispatch, scope, controller);
    } catch (error) {
      if (scope.owns(controller) && !(error instanceof DOMException && error.name === "AbortError")) {
        dispatch({ type: "failed", requestId, error: errorMessage(error) });
      }
    } finally {
      if (scope.finish(controller)) dispatch({ type: "finished" });
    }
  }
  return submit;
}
