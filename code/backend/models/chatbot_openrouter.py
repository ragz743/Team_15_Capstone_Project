"""A Wrapper for the langchain ChatOpenRouter class to be instantiated by the model factory."""

import os

from backend.models._chatbot_base import _BaseChatbot
from langchain_openrouter import ChatOpenRouter


class ChatbotOpenRouter(_BaseChatbot):
    """Factory compatible ChatOpenRouter wrapper."""

    def __init__(self, kwargs) -> None:
        """Create an instance of the ChatbotOpenRouter."""
        model: str = kwargs.pop("model")
        self._model = ChatOpenRouter(
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),  # type: ignore (can't get SecretStr type)
            **kwargs,
        )

    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        response = self._model.invoke(messages)

        all_responses: str = ""
        match response.content:
            case [msgs]:
                if isinstance(msgs, str):
                    all_responses = "\n".join(msgs)
                else:
                    # TODO (Any): figure out what kind of responses return a dict
                    # is this handling ok or are we missing out on info?
                    all_responses = "\n".join([str(v) for v in msgs.values()])

            case str(msg):  # must be string
                all_responses = msg

        return all_responses
