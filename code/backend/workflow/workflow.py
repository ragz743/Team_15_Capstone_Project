"""AgWeatherNet Chatbot Workflow."""

from typing import Annotated, Literal, TypedDict

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

    query_type: QueryType
    reworded_query: str = Field(description="A rewording of the user's input as a clear standalone query.")


class ChatState(TypedDict):
    """The state object that will be passed between nodes in the graph."""

    messages: Annotated[list, message.add_messages]
    sub_queries: list[QueryClassification]


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

        # connect nodes with edges
        graph.add_edge(START, "query_classifier")
        graph.add_conditional_edges("query_classifier", self._route_query)
        for node in (
            "query_current",
            "query_forecast",
            "query_historical",
            "query_miscellaneous",
        ):
            graph.add_edge(node, "chatbot_summarize")
        graph.add_edge("chatbot_summarize", END)

        return graph.compile(checkpointer=self.checkpointer)

    def _query_classifier(self, state: ChatState) -> dict:
        """Given user input classify it before taking action."""
        raise NotImplementedError

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
