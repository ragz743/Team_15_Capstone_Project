"""A Wrapper for the github copilot api to be instantiated by the model factory."""

import asyncio

from backend.models._chatbot_base import _BaseChatbot
from copilot import CopilotClient
from copilot.rpc import PermissionDecisionReject
from copilot.session_events import AssistantMessageData


class ChatbotCopilot(_BaseChatbot):
    """Factory compatible ChatOpenRouter wrapper."""

    def __init__(self, kwargs) -> None:
        """Create an instance of the ChatbotOpenRouter."""
        self._model: str = kwargs.pop("model")

    async def _async_invoke(self, messages: str) -> str:
        """Asynchronously invoke copilot model returning the response."""
        async with CopilotClient() as client:
            async with await client.create_session(
                on_permission_request=(lambda _req, _invok: PermissionDecisionReject()),  # deny all
                model=self._model,
            ) as session:
                response = await session.send_and_wait(messages)

                # if no response (it returned nothing) then throw
                if response is None:
                    msg = f"Copilot call returned nothing with input:\n{messages}"
                    raise ValueError(msg)

                # AssistantMessageData should be final result of question
                # if some other type returned something funky happened, throw!
                match response.data:
                    case AssistantMessageData(content=content):
                        return content
                    case _ as session_data:  # if any other session event type (indicating an err)
                        msg = f"unexpected event type returned, found {type(session_data).__name__}"
                        raise TypeError(msg)

    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        # Copilot sdk calls must be async, Chatbot base is currently synchronous
        # so solution for now is to force async calls to be sequential w/ wrapper
        return asyncio.run(self._async_invoke("\n".join(messages)))
