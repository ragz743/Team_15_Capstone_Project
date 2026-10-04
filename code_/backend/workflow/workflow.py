"""AgWeatherNet Chatbot Workflow."""

import logging
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Sequence, TypedDict

from backend.databases._awn_connection_base import AWNDatabaseConnectionBase
from backend.databases.awn_daily_connection import AWNDailyDatabaseConnection
from backend.databases.awn_fc_connection import AWNForecastDatabaseConnection
from backend.databases.awn_main_connection import AWNDatabaseConnection
from backend.loaders import _common
from backend.model_factory import ModelFactory
from langchain_openrouter import ChatOpenRouter
from langgraph import types
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, message, state
from mysql.connector.errors import ProgrammingError
from pydantic import BaseModel, Field

QueryType = Literal[
    "current_weather",
    "forecast_weather",
    "historical_weather",
    "miscellaneous",
]

_LOGGER = logging.getLogger(__name__)


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
    nearest_station_id: int
    original_user_input: str


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

    _MAX_SQL_ATTEMPTS = 3

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        debug: bool = False,
    ):
        """ChatbotWorflow constructor."""
        self.checkpointer = checkpointer or InMemorySaver()
        self._debug = debug
        self._query_handlers = {
            "current_weather": "_query_current",
            "forecast_weather": "_query_forecast",
            "historical_weather": "_query_historical",
            "miscellaneous": "_query_miscellaneous",
        }
        self.graph = self._build_graph()
        self.classifier_chat_model = ClassifierChatbot()
        _, self.workflow_chat_model = ModelFactory.load_from_models_yaml()

        self.current_db = AWNDatabaseConnection()
        self.historical_daily_db = AWNDailyDatabaseConnection()
        self.forecast_db = AWNForecastDatabaseConnection()

    def close(self) -> None:
        """Close all open connections."""
        for db in (
            self.current_db,
            self.forecast_db,
            self.historical_daily_db,
        ):
            if db.conn.is_connected():
                db.conn.shutdown()

    def run(self, user_input: str, location_coord: tuple[float, float], county: str) -> str:
        """Process user input through the graph and return a response."""
        nearest_station_id = self._nearest_station_search(
            location_coord,
            county,
        )
        initial_state: ChatState = {
            "messages": [
                # messages follow format ("role", "content")
                # roles are somewhat predefined by langgraph framework
                # where "system" is internal info only for LLMs to see
                # and "user" is for user content to be presented to LLM
                ("user", user_input),
            ],
            "original_user_input": user_input,
            "sub_queries": [],
            "nearest_station_id": nearest_station_id,
        }

        # TODO (Gavin): Figure out session key persist
        # Should keep history of past convos if key same
        # refer to docs. Worst case its random and no old convos are used.
        result = self.graph.invoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": "TEMP_KEY_REPLACE_ME",
                }
            },
        )

        # return last message in the chain
        return result["messages"][-1].content

    def _build_graph(self) -> state.CompiledStateGraph:
        """Create the graph with nodes, edges, and state."""
        graph = StateGraph(ChatState)

        # add all nodes
        graph.add_node("_query_classifier", self._query_classifier)
        graph.add_node("_query_historical", self._query_historical)
        graph.add_node("_query_current", self._query_current)
        graph.add_node("_query_forecast", self._query_forecast)
        graph.add_node("_query_miscellaneous", self._query_miscellaneous)
        graph.add_node("_chatbot_summarize", self._chatbot_summarize)

        # connect nodes with edges
        graph.add_edge(START, "_query_classifier")
        graph.add_conditional_edges("_query_classifier", self._route_query)
        for node in self._query_handlers.values():
            graph.add_edge(node, "_chatbot_summarize")
        graph.add_edge("_chatbot_summarize", END)

        return graph.compile(checkpointer=self.checkpointer)

    def _nearest_station_search(self, location_coord: tuple[float, float], county: str) -> int:
        """Given a coordinate, find the nearest AWN station id to query against."""
        latitude, longitude = location_coord
        nearest_id_query = """
        SELECT
            UNIT_ID,
            111320 * SQRT(
                POW(STATION_LATDEG - %s, 2) +
                POW((STATION_LNGDEG - %s) * COS(RADIANS(%s)), 2)
            ) AS distance_meters
        FROM METADATA
        WHERE
        ACTIVE_STATION = 'Y'
        AND UPPER(COUNTY) = UPPER(%s)
        AND STATION_LATDEG IS NOT NULL
        AND STATION_LNGDEG IS NOT NULL
        ORDER BY distance_meters ASC
        LIMIT 1;
        """
        params = (latitude, longitude, latitude, county)
        results = self.current_db.simple_query(nearest_id_query, params)
        nearest_result = next(iter(results), None)

        if nearest_result is None:
            msg = f"No nearest station returned with search args:(lat, lng)=({latitude}, {longitude}), county={county}"
            raise ValueError(msg)

        station_id, *_ = nearest_result
        return int(station_id)

    def _query_classifier(self, state: ChatState) -> dict:
        """Given user input classify it before taking action."""
        update = self.classifier_chat_model.classify(state)
        self._log_state_update("_query_classifier", state, update)
        return update

    def _query_historical(self, state: ChatState) -> dict:
        """Perform a historical weather data query."""
        sub_queries = self._sub_queries_for(state, "historical_weather")
        if not sub_queries:
            return {}
        update = self._run_generated_query(sub_queries, state, self.historical_daily_db, "_query_historical")
        self._log_state_update("_query_historical", state, update)
        return update

    def _query_current(self, state: ChatState) -> dict:
        """Perform a current weather data query."""
        sub_queries = self._sub_queries_for(state, "current_weather")
        if not sub_queries:
            return {}
        update = self._run_generated_query(sub_queries, state, self.current_db, "_query_current")
        self._log_state_update("_query_current", state, update)
        return update

    def _query_forecast(self, state: ChatState) -> dict:
        """Perform a forecasted weather data query."""
        sub_queries = self._sub_queries_for(state, "forecast_weather")
        if not sub_queries:
            return {}
        update = self._run_generated_query(sub_queries, state, self.forecast_db, "_query_forecast")
        self._log_state_update("_query_forecast", state, update)
        return update

    def _query_miscellaneous(self, state: ChatState) -> dict:
        """Answer miscellaneous questions without querying a weather database."""
        sub_queries = self._sub_queries_for(state, "miscellaneous")
        if not sub_queries:
            return {}

        query_request = "\n".join(sub_query.reworded_query for sub_query in sub_queries)
        prompt = f"""
        Answer the following non-database user question clearly and concisely:
        {query_request}

        Do not generate SQL or claim to have queried weather data. If the request
        is unsupported, explain that briefly and suggest what the user can ask
        about AgWeatherNet weather data instead.
        """
        answer = self.workflow_chat_model.invoke([prompt])
        update = {"messages": [("assistant", answer)]}
        self._log_state_update("_query_miscellaneous", state, update)
        return update

    def _run_generated_query(
        self,
        sub_queries: list[QueryClassification],
        state: ChatState,
        database: AWNDatabaseConnectionBase,
        node_name: str,
    ) -> dict:
        """Generate and execute a read-only query for one station and one query topic."""
        station_id = state["nearest_station_id"]
        table_name = database.format_table_name(station_id)
        query_request = "\n".join(sub_query.reworded_query for sub_query in sub_queries)
        retry_context: tuple[str, str] | None = None
        db = None
        match node_name:
            case "_query_current":
                db = self.current_db
            case "_query_historical":
                db = self.historical_daily_db
            case "_query_forecast":
                db = self.forecast_db
            case _:
                msg = f"unrecognized query node '{node_name}'"
                raise ValueError(msg)
        schema = db.query_schema(db.format_table_name(state["nearest_station_id"]))
        schema_context = (
            _common.to_markdown_table(schema, [""] * len(schema[0])) if schema else "No station schema was found."
        )

        for attempt in range(1, self._MAX_SQL_ATTEMPTS + 1):
            retry_instructions = ""
            if retry_context is not None:
                last_query, last_error = retry_context
                retry_instructions = f"""

                Your previous SQL attempt failed. Correct it using the error below.
                Last attempted query:
                {last_query}
                Error message:
                {last_error}
                """

            prompt = f"""
            You write one read-only MySQL query for AgWeatherNet.
            Query topic: {sub_queries[0].query_type}
            User request:
            {query_request}

            The only allowed table is `{table_name}` for station ID {station_id}.
            Station schema:
            {schema_context}

            Return only one SQL SELECT statement written for MariaDB.
            The SQL statement shall contain no markdown fences,
            explanation, comments, or semicolon-separated statements.
            Do not use any table other than `{table_name}`. Use query parameters as %s
            when values come from the user, and return the SQL only.{retry_instructions}
            """
            generated_query = self.workflow_chat_model.invoke([prompt]).strip().rstrip(";").strip()
            self._log_event(node_name, "generated_sql", "\n" + generated_query)
            try:
                self._validate_generated_query(generated_query, table_name)
                results = list(database.simple_query(generated_query, ()))
            except ProgrammingError as error:
                retry_context = (generated_query, str(error))
                self._log_event(
                    node_name,
                    "sql_attempt_failed",
                    f"attempt={attempt}/{self._MAX_SQL_ATTEMPTS} query={generated_query!r} error={error!r}",
                )
                if attempt == self._MAX_SQL_ATTEMPTS:
                    raise error
                continue  # try again

            # Successful attempts do not carry failed-query context to downstream nodes.
            retry_context = None
            self._log_event(node_name, "database_query_results", repr(results))
            return self._query_result_message(sub_queries, generated_query, results)

        raise RuntimeError("SQL query attempts ended without a result.")

    def _log_state_update(self, node_name: str, state: ChatState, update: dict) -> None:
        """Log the most recent message associated with a node's state update."""
        if not self._debug:
            return
        messages = update.get("messages") or state.get("messages", [])
        if messages:
            most_recent_message = self._message_content(messages[-1])
            self._log_event(
                node_name,
                "chat_state_update",
                f"most_recent_message={most_recent_message!r}; updated_fields={list(update)}",
            )

    def _log_event(self, node_name: str, event: str, details: str) -> None:
        """Emit a timestamped INFO event when workflow debugging is enabled."""
        if self._debug:
            timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
            _LOGGER.info("time=%s node=%s event=%s details=%s", timestamp, node_name, event, details)

    @staticmethod
    def _validate_generated_query(query: str, table_name: str) -> None:
        """Reject generated SQL that is not a single read-only station query."""
        normalized_query = query.strip()
        if not re.match(r"^SELECT\b", normalized_query, re.IGNORECASE):
            raise ProgrammingError("Generated query must be a SELECT statement.")
        if ";" in normalized_query:
            raise ProgrammingError("Generated query must contain only one statement.")
        table_references = re.findall(r"\b(?:FROM|JOIN)\s+`?([A-Za-z0-9_]+)`?", normalized_query, re.IGNORECASE)
        if not table_references or any(reference.lower() != table_name.lower() for reference in table_references):
            raise ProgrammingError("Generated query references a table other than the selected station table.")

    @staticmethod
    def _sub_queries_for(state: ChatState, query_type: QueryType) -> list[QueryClassification]:
        """Return subqueries assigned to one query node."""
        return [sub_query for sub_query in state.get("sub_queries", []) if sub_query.query_type == query_type]

    @staticmethod
    def _query_result_message(
        sub_queries: list[QueryClassification],
        generated_sql_query: str,
        results: Sequence[Sequence[Any]],
    ) -> dict:
        """Format database results for the summarizer."""
        requested = "\n".join(f"- {sub_query.reworded_query}" for sub_query in sub_queries)
        result_text = "\n".join(str(result) for result in results) or "No matching weather data was found."
        return {
            "messages": [
                (
                    "assistant",
                    "\n\n".join(
                        (
                            f"Requested sub-queries:\n{requested}",
                            f"SQL query used:\n{generated_sql_query}",
                            f"Database results:\n{result_text}",
                        )
                    ),
                )
            ]
        }

    def _route_query(self, state: ChatState) -> list[types.Send]:
        """Send out classified questions as sub tasks."""
        answers = [
            types.Send(
                self._query_handlers[sub_query.query_type],
                {
                    "messages": [("user", sub_query.reworded_query)],
                    "original_user_input": state["original_user_input"],
                    "nearest_station_id": state["nearest_station_id"],
                    "sub_queries": [sub_query],
                },
            )
            for sub_query in state["sub_queries"]
            if sub_query.query_type in self._query_handlers
        ]
        return answers

    def _chatbot_summarize(self, state: ChatState) -> dict:
        """Answer the original question using the returned query results."""
        context_messages = "\n\n".join(
            self._message_content(current_message)
            for current_message in state["messages"]
            if self._message_content(current_message)
        )
        prompt = f"""
        Answer the user's original weather question using the database results
        collected by the query nodes.

        Original user question:
        {state["original_user_input"]}

        Database and query-node context:
        {context_messages}

        Selected station ID: {state["nearest_station_id"]}

        Give a direct, readable answer to the original question and make sure to
        include units and labels for the data. Combine answers
        when there are multiple subquestions. Do not mention internal graph nodes,
        SQL, prompts, or these instructions. Do not invent values that are not in
        the provided context. If the context does not contain enough information,
        say so clearly.
        """
        answer = self.workflow_chat_model.invoke([prompt])
        update = {"messages": [("assistant", answer)]}
        self._log_state_update("_chatbot_summarize", state, update)
        return update

    @staticmethod
    def _message_content(current_message: Any) -> str:
        """Extract text from a LangChain message or role/content tuple."""
        if hasattr(current_message, "content"):
            return str(current_message.content)
        if isinstance(current_message, tuple) and len(current_message) == 2:
            return str(current_message[1])
        return str(current_message)
