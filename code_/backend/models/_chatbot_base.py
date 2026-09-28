"""The base class for a chatbot model."""

import json
from abc import ABC, abstractmethod


class _BaseChatbot(ABC):
    """The chatbot model base class."""

    @abstractmethod
    def invoke(self, messages: list[str]) -> str:
        """Pass a list of messages and gets responses from the model."""
        # TODO (Any): Add abstract methods, what does every chatbot need to do?
        raise NotImplementedError

    def invoke_json(self, instructions: str, payload: dict, schema: dict) -> str:
        """Provide a JSON contract for local/test models that do not offer constrained decoding."""
        prompt = instructions + "\nSchema:\n" + json.dumps(schema)
        prompt += "\nInput JSON:\n" + json.dumps(payload, ensure_ascii=False, default=str)
        return self.invoke([prompt])
