import { useReducer, useState } from "react";
import ChatWorkspace from "./components/ChatWorkspace";
import { useChatSubmission } from "./hooks/useChatSubmission";
import { useConversationHistory } from "./hooks/useConversationHistory";
import { conversationReducer, initialState } from "./lib/conversationState";
import { RequestScope } from "./lib/requestScope";

export default function App() {
  const [state, dispatch] = useReducer(conversationReducer, initialState);
  const [scope] = useState(() => new RequestScope());
  const history = useConversationHistory(state, dispatch, scope);
  const submit = useChatSubmission(state, dispatch, scope);

  return (
    <ChatWorkspace
      messages={state.messages}
      draft={state.draft}
      mode={state.mode}
      onModeChange={(value) => dispatch({ type: "mode", value })}
      isSending={state.busy}
      ready={state.ready}
      notice={state.notice}
      point={state.point}
      onPointChange={(value) => dispatch({ type: "point", value })}
      history={{
        conversations: state.conversations,
        selectedId: state.conversationId,
        onSelect: history.open,
        onRefresh: history.refresh,
        onLoadOlder: state.hasOlder ? () => history.refresh(true) : undefined,
        onLoadEarlier:
          state.conversationId && state.nextBefore
            ? () => history.open(state.conversationId!, state.nextBefore!)
            : undefined,
      }}
      onDraftChange={(value) => dispatch({ type: "draft", value })}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      onNewConversation={history.clear}
      onRetry={(message) => void submit(message)}
    />
  );
}
