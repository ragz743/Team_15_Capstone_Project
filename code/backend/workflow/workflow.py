"""AgWeatherNet Chatbot Workflow."""

from datetime import datetime
from typing import Annotated, Literal, TypedDict

from langchain_openrouter import ChatOpenRouter
from langgraph import types
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, message, state
from pydantic import BaseModel, Field

QueryType = Literal[
    "current_weather",
    "forecast_weather",
    "historical_weather",
    "miscellaneous",
]


class QueryClassification(BaseModel):
    """A standalone query categorized as a variant of the QueryType."""

    query_type: QueryType = Field(
        description=(
            "current_weather: conditions right now or 'today' with no forecast intent. "
            "forecast_weather: any future-looking question (tomorrow, this week, will it...). "
            "historical_weather: past dates/periods (yesterday, last month, on this date last year). "
            "miscellaneous: anything not about specific weather conditions/timing, "
            "e.g. site usage, definitions, or unsupported requests."
        )
    )
    reworded_query: str = Field(description="The user's intent restated as a clear, standalone, unambiguous query.")


class QueryClassifications(BaseModel):
    """One or more standalone queries extracted from the user's input."""

    sub_queries: list[QueryClassification] = Field(
        min_length=1,
        description="Every distinct weather question found in the user's input.",
    )


class ChatState(TypedDict):
    """The state object that will be passed between nodes in the graph."""

    messages: Annotated[list, message.add_messages]
    sub_queries: list[QueryClassification]


class ClassifierChatbot:
    """Chatbot for classifying questions with structured output."""

    _CLASSIFIER_SYSTEM_PROMPT = f"""
    Today's date is {datetime.now():%Y-%m-%d}.
    You are a weather data research assistant. Break the user's input into one
    or more standalone weather-related queries, and classify each one.

    If the input contains multiple distinct questions, return one entry per
    question. If it's a single question, return one entry.

    Examples:
    - "What's it like outside and will it rain tomorrow?" ->
    two entries: current_weather ("What is the current weather?"),
    forecast_weather ("Will it rain tomorrow?")
    - "How much rain did we get last week?" ->
    one entry: historical_weather ("How much rain fell in the last week?")
    - "What's a dew point?" ->
    one entry: miscellaneous ("What is a dew point?")
    """

    def __init__(self) -> None:
        """ClassifierChatbot Constructor."""
        self._model = ChatOpenRouter(model="openrouter/free", temperature=0).with_structured_output(
            QueryClassifications
        )

    def classify(self, state: ChatState) -> dict:
        """Make a call to the llm."""
        result = self._model.invoke(
            [
                ("system", self._CLASSIFIER_SYSTEM_PROMPT),
                *state["messages"],
            ]
        )

        return {"sub_queries": result.sub_queries}  # type: ignore


class ChatbotWorkflow:
    """The class for configuration of the chatbot workflow."""

    def __init__(self, checkpointer: BaseCheckpointSaver):
        """ChatbotWorflow constructor."""
        self.checkpointer = checkpointer or InMemorySaver()
        self._query_handlers = {
            "current_weather": "_query_current",
            "forecast_weather": "_query_forecast",
            "historical_weather": "_query_historical",
            "miscellaneous": "_query_miscellaneous",
        }
        self.graph = self._build_graph()
        self.classifier_chat_model = ClassifierChatbot()

    def run(self, user_input: str) -> str:
        """Process user input through the graph and return a response."""
        initial_state = {"messages": [("user", user_input)]}
        result = self.graph.invoke(initial_state)

        # return last message in the chain
        return result["messages"][-1].content

    def _build_graph(self) -> state.CompiledStateGraph:
        """Create the graph with nodes, edges, and state."""
        graph = StateGraph(ChatState)

        # add all nodes
        graph.add_node("query_classifier", self._query_classifier)
        graph.add_node("query_historical", self._query_historical)
        graph.add_node("query_current", self._query_current)
        graph.add_node("query_forecast", self._query_forecast)
        graph.add_node("query_miscellaneous", self._query_miscellaneous)
        graph.add_node("chatbot_summarize", self._chatbot_summarize)

        # connect nodes with edges
        graph.add_edge(START, "query_classifier")
        graph.add_conditional_edges("query_classifier", self._route_query)
        for node in self._query_handlers.values():
            graph.add_edge(node, "chatbot_summarize")
        graph.add_edge("chatbot_summarize", END)

        return graph.compile(checkpointer=self.checkpointer)

    def _query_classifier(self, state: ChatState) -> dict:
        """Given user input classify it before taking action."""
        return self.classifier_chat_model.classify(state)

    def _query_historical(self, state: ChatState) -> dict:
        """Perform a historical weather data query."""
        raise NotImplementedError

    def _query_current(self, state: ChatState) -> dict:
        """Perform a current weather data query."""
        raise NotImplementedError

    def _query_forecast(self, state: ChatState) -> dict:
        """Perform a forecasted weather data query."""
        raise NotImplementedError

    def _query_miscellaneous(self, state: ChatState) -> dict:
        """Attempt to perform a miscellaneous query."""
        raise NotImplementedError

    def _route_query(self, state: ChatState) -> list[types.Send]:
        """Send out classified questions as sub tasks."""
        answers = [
            types.Send(
                self._query_handlers[sub_query.query_type],
                {"messages": [("user", sub_query.reworded_query)]},
            )
            for sub_query in state["sub_queries"]
        ]
        return answers

    def _chatbot_summarize(self, state: ChatState) -> dict:
        """Answer the original question using the returned query results."""
        raise NotImplementedError
