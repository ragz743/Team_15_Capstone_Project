"""Four-stage prompt-chaining RAG orchestrator for the AgWeatherNet AI Chatbot."""

# Stage 1: Intent Classification
#   Classify the user query into one of: live | historical | forecast | aggregate | schema | off_topic
#   Also extract station hints, date ranges, and metric names.abs
#   ff-topic queries and rejected here without hitting the DB (FR-5).

# Stage 2: Station Disambiguation [conditional]
#   If Stage 1 returned a vague station name, match it against the know AgWeatherNet station list or ask
#   the user to clarify (FR-6, FR-11, US6, US11). Skipped when the session already holds a confirmed station_id

# Stage 3: Semantic Retrieval
#   Use the classified intent + resolved station_id as JSONB metadata filters and run cosine-similarity search
#   against the pgvector store. This is the pure RAG retrieval step - NOT NL2SQL (FR-4, NFR-2)

# Stage 4: Answer Synthesis
#   Combine [system rules + retrieved context + conversation history + user query] into a single LLM call that
#   produces the final answer. Output rules enforce: units & timestamps (FR-32), no raw data dumps (FR-34), no
#   precise station coordinates (FR-35), source citations (FR-31), clarifying questions when needed (FR-28),
#   domain guardrails (FR-5), and follow-up context (FR-29).

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..databases.vector_store import RetrievedChunk, VectorStore

logger = logging.getLogger(__name__)

# DOMAIN CONSTANTS

VALID_INTENTS = frozenset(
    {"live", "historical", "forecast", "aggregate", "schema"}
)
OFF_TOPIC = "off_topic"
MAX_HISTORY_TURNS = (
    6  # Maximum conversation turns retained for follow-up context (FR-29).
)

# PROMPT TEMPLATES

# Stage 1 - Intent classification
INTENT_SYSTEM = """\
  You are a query router for the AgWeatherNet agricultural weather database. Your ONLY job is to classify the user query
  and extract parameters. Output ONLY valid JSON - no prose, no markdown fences.

  JSON schema:
  {{
    "intent":    "<live|historical|forecast|aggregate|schema|off_topic>",
    "station_hint": "<station name / location the user mentioned, or null>",
    "date_start":   "<ISO-8601 date or null>",
    "date_end":     "<ISO-8601 date or null>",
    "metric":       "<weather metric name or null (e.g. temperature, precipitation)>",
    "reason":       "<one sentence explanation>"
  }}

  Classification rules:
    live       -> current / now / today / real-time weather conditions
    historical -> past conditions with a specific date or date range
    forecast   -> future / upcoming / tomorrow / next N days
    aggregate  -> sum, average, min, max, total over a time range
    schema     -> questions about available stations, metrics, or data
    off_topic  -> anything outside AgWeatherNet's Washington State dataset
                  (sports, cooking, weather elsewhere, general knowledge, etc.)

  Today's date (UTC): {today}
  """

# Stage 2 - Station disambiguation
DISAMBIG_SYSTEM = """\
  You are a weather station resolver for AgWeatherNet.
  Match the user's location hint to the official AgWeatherNet station list.

  Output ONLY valid JSON - no prose.

  JSON schema when a match is found:
  {{"station_id": "<id>", "station_name": "<display name>", "ask_user": false}}

  JSON schema when multiple equally-close stations are found:
  {{
    "station_id": null,
    "candidates": [{{"id": "<id>", "name": "<name>"}}, ...],
    "ask_user": true,
    "clarification_message": "<explain no station found; suggest alternatives>"
  }}

  JSON schema for when no matches are found:
  {{"station_id": null, "candidates": [], "ask_user": false}}

  Known AgWeatherNet stations:
  {station_list_json}
  """

ANSWER_SYSTEM = """\
  You are the AgWeatherNet AI Chatbot assistant.
  You answer questions about Washington State agricultural weather data from AgWeatherNet's network of over 300
  weather stations.

  You MUST follow every rule below without exception.

  -- DOMAIN RULES ---------------------------------------------------------------------------------------------
  1. Only answer questions about AgWeatherNet weather data for Washington State. Politely decline anything
     else and explain what you can help with.
  2. Base every answer strictly on the CONTEXT provided below. Never invent, estimate, or hallucinate weather
     values.
  3. If the CONTEXT does not contain enough information to answer, say so clearly and suggest the user narrow
     their query or pick a different station. Do not guess.

  -- RESPONSE FORMAT RULES ------------------------------------------------------------------------------------
  4. Always include measurement units (°F, °C, inches, mph, % RH, etc.) and the exact timestamp or time
     window for every numeric value.
  5. Always cite the station name and data source for numeric values. Example: "At Pullman (pullman_wsda),
     temperature on 2026-04-17 was 54°F."
  6. Do NOT output raw CSV, JSON, arrays, or database dumps. Respond in clear, conversational prose or a
     brief labelled summary.
  7. Do NOT reveal precise GPS coordinates of weather stations. Use county or region names only.
  8. Keep responses concise and free of technical jargon. Non-technical growers and extension agents are
     your primary audience.

  -- INTERACTION RULES ----------------------------------------------------------------------------------------
  9. If the query is ambiguous (missing station, unclear time range, or unclear metric), ask one focused
     clarifying question before answering.
  10. Use the CONVERSATION HISTORY to maintain context across follow-up questions (e.g. keep the last station
      selected unless the user changes it).
  11. For basic weather / agriculture definitions (e.g. "what are growing degree days?"), answer from your
      agricultural knowledge - no retrieval needed.

  -- RETRIEVED CONTEXT ----------------------------------------------------------------------------------------
  {context}

  -- CONVERSATION HISTORY -------------------------------------------------------------------------------------
  {history}
  """


# DATA-TRANSFER OBJECTS


@dataclass
class IntentResult:
    """Output of Stage 1: intent classification. Not part of the public API."""

    intent: str
    station_hint: str | None
    date_start: str | None
    date_end: str | None
    metric: str | None
    reason: str


@dataclass
class PipelineResponse:
    """Final output of RAGPipeline.run().

    Attributes
    ----------
    answer: Text to display in the chatbot UI.
    intent: Resolved intent label.
    station_id: Resolved station identifier (if known).
    retrieved_chunks: Chunks injected into the LLM prompt (for logging / FR-39).
    needs_clarification: True when 'answer' IS the clarifying question itself.
    latency_ms: Total wall-clock time for the pipeline call.
    stage_timings: Per-stage breakdown (for FR-39 metric logging).

    """

    answer: str
    intent: str
    station_id: str | None
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    needs_clarification: bool = False
    latency_ms: float = 0.0
    stage_timings: dict[str, float] = field(default_factory=dict)


# RAGPipeline


class RAGPipeline:
    """Orchestrates the four stage prompt-chaining RAG pipeline.

    Designed to plug into the existing modular model architecture: pass in any _BaseEmbedding and
    _BaseChatbot subclass.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_model: Any,
        chatbot_model: Any,
        known_stations: list[dict],
        today: str = "",
        max_context_chunks: int = 6,
    ) -> None:
        """Initialize the RAG pipeline.

        Parameters
        ----------
        vector_store:
            Connected VectorStore instance.
        embedding_model:
            Embedding model (from models.yaml).
        chatbot_model:
            Chatbot model (from models.yaml).
        known_stations:
            Full AWN station list for disambiguation.
        today:
            ISO-8601 date string injected into intent prompt.
        max_context_chunks:
            Maximum retrieved chunks passes to the LLM. Balances context
            quality vs. token budget.

        """
        self.vs = vector_store
        self.embed = embedding_model
        self.chat = chatbot_model
        self.stations = known_stations
        self.today = today
        self.max_chunks = max_context_chunks

    # PUBLIC API (ENTRY POINT)

    def run(
        self,
        user_query: str,
        conversation_history: list[dict] | None = None,
        resolved_station_id: str | None = None,
    ) -> PipelineResponse:
        """Execute the full four-stage RAG pipeline for a single user message.

        Parameters
        ----------
        user_query:
            Raw NL query from the chatbot UI input box (FR-1).
        conversation_history:
            Prior turns as [{"role": "user"|"assistant", "content": "..."}, ...].
            Used by Stage 4 for follow-up context (FR-29).
        resolved_station_id:
            Station already confirmed in the current session. When provided,
            Stage 2 is skipped, which saves one LLM round-trip (NFR-1).

        Returns
        -------
        PipelineResponse ready to be serialized and returned to the UI.

        """
        t_start = time.monotonic()
        history = list[dict] = conversation_history or []
        timings: dict[str, float] = {}

        # Stage 1: Intent Classification
        t0 = time.monotonic()
        intent = self._stage1_classify(user_query)
        timings["stage1_intent_ms"] = (time.monotonic() - t0) * 1000
        logger.info(
            "RAGPipeline Stage1: intent=%s station_hint=%s metric=%s reason=%s",
            intent.intent,
            intent.station_hint,
            intent.metric,
            intent.reason,
        )

        # Guard: off-topic -> short-circuit without touching the DB (FR-5)
        if intent.intent == OFF_TOPIC:
            return PipelineResponse(
                answer=(
                    "I can only assist with weather data from AgWeatherNet's Washington State "
                    "station network. Please ask a question about weather conditions, forecasts, or "
                    "station data."
                ),
                intent=OFF_TOPIC,
                station_id=None,
                needs_clarification=False,
                latency_ms=(time.monotonic() - t_start) * 1000,
                stage_timings={
                    **timings,
                    "stage2_disambig_ms": 0.0,
                    "stage3_retrieval_ms": 0.0,
                    "stage4_synthesis_ms": 0.0,
                },
            )

        # Stage 2: Station Diambiguation
        t0 = time.monotonic()
        station_id = resolved_station_id

        if station_id is None and intent.station_hint:
            disambig = self._stage2_resolve_station(intent.station_hint)
            logger.info("RAGPipeline Stage2: disambig=%s", disambig)

            if disambig.get("ask_user"):
                timings["stage2_disambig_ms"] = (time.monotonic() - t0) * 1000

                # Return the clarifying question - do not query the DB yet
                return PipelineResponse(
                    answer=disambig["clarification_message"],
                    intent=intent.intent,
                    station_id=None,
                    needs_clarification=True,
                    latency_ms=(time.monotonic() - t_start) * 1000,
                    stage_timings={
                        **timings,
                        "stage3_retrieval_ms": 0.0,
                        "stage4_synthesis_ms": 0.0,
                    },
                )
            station_id = disambig.get("station_id")

        timings["stage2_disambig_ms"] = (time.monotonic() - t0) * 1000

        # Stage 3: Semantic Retrieval
        t0 = time.monotonic()
        chunks = self._stage3_retrieve(
            user_query=user_query,
            intent=intent.intent,
            station_id=station_id,
            metric=intent.metric,
        )
        timings["stage3_retrieval_ms"] = (time.monotonic() - t0) * 1000
        logger.info(
            "RAGPipeline Stage3: retrieved %d chunks (station=%s data_type=%s)",
            len(chunks),
            station_id,
            intent.intent,
        )

        # Stage 4: Answer Synthesis
        t0 = time.monotonic()
        answer = self._stage4_synthesize(
            user_query=user_query,
            chunks=chunks,
            history=history,
        )
        timings["stage4_synthesis_ms"] = (time.monotonic() - t0) * 1000

        total_ms = (time.monotonic() - t_start) * 1000
        logger.info("RAGPipeline complete in %.0f ms", total_ms)

        return PipelineResponse(
            answer=answer,
            intent=intent.intent,
            station_id=station_id,
            retrieved_chunks=chunks,
            needs_clarification=False,
            latency_ms=total_ms,
            stage_timings=timings,
        )

    # STAGE IMPLEMENTATIONS

    def _stage1_classify(self, user_query: str) -> IntentResult:
        """Stage 1: Single LLM call to classify intent and extract parameters.

        The structured JSON output is parsed and validated. Parse errors default to off_topic
        so the pipeline degrades gracefully.
        """
        system = INTENT_SYSTEM.format(today=self.today)
        raw = self.chat.complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_query},
            ]
        )
        try:
            data = _parse_json(raw)
            intent = data.get("intent", OFF_TOPIC)
            # Validate intent; unknown values become off_topic
            if intent not in VALID_INTENTS:
                intent = OFF_TOPIC
            return IntentResult(
                intent=intent,
                station_hint=data.get("station_hint"),
                date_start=data.get("date_start"),
                date_end=data.get("date_end"),
                metric=data.get("metric"),
                reason=data.get("reason", ""),
            )
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning(
                "RAGPipeline Stage1: JSON parse error (%s) - defaulting to off_topic.",
                exc,
            )
            return IntentResult(
                intent=OFF_TOPIC,
                station_hint=None,
                date_start=None,
                date_end=None,
                metric=None,
                reason="parse error",
            )

    def _stage2_resolve_station(self, station_hint: str) -> dict:
        """Stage 2: Resolve station from location hint.

        Matches a hint to a station_id or returns a clarification question (FR-6, FR-11).
        """
        system = DISAMBIG_SYSTEM.format(
            station_list_json=json.dumps(self.stations, indent=2)
        )
        raw = self.chat.complete(
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"User location hint: {station_hint}",
                },
            ]
        )
        try:
            return _parse_json(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "RAGPipeline stage2: JSON parse failed (%s) - no station resolved.",
                exc,
            )
            # Fail open: proceed without a station_id rather than crashing
            return {"station_id": None, "ask_user": False}

    def _stage3_retrieve(
        self,
        user_query: str,
        intent: str,
        station_id: str | None,
        metric: str | None,
    ) -> list[RetrievedChunk]:
        """Stage 3: Retrieve relevant chunks.

        Embed the user query and run metadata-filtered semantic search against the
        pgvector store.

        This is the RAG retrieval step - pure cosine-similarity search, not NL2SQL.
        Aggregate queries also pull schema context so the LLM understands the available
        aggregation columns.
        """
        query_vec: list[float] = self.embed.embed(user_query)

        if intent == "aggregate":
            # Pull both aggregate context and schema context (FR-10)
            return self.vs.search_multi_type(
                query_vec,
                data_types=["aggregate", "schema"],
                station_id=station_id,
                metric=metric,
                top_k=self.max_chunks,
            )

        return self.vs.search(
            query_vec,
            data_type=intent,
            station_id=station_id,
            metric=metric,
            top_k=self.max_chunks,
        )

    def _stage4_synthesize(
        self,
        user_query: str,
        chunks: list[RetrievedChunk],
        history: list[dict],
    ) -> str:
        """Stage 4: Generate final response.

        Build the grounded prompt from retrieved chunks and conversation
        history, then call the chatbot LLM.

        Context is formatted with source attribution headers so the LLM can cite
        sources in its answer (FR-31).
        """
        # Build context block with attribution headers (FR-31)
        context_parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            m = chunk.metadata
            header = (
                f"[Source {i}] "
                f"  station={m.station_id or 'N/A'} | "
                f"  type={m.data_type or 'N/A'} | "
                f"  table={m.source_table or 'N/A'} | "
                f"  similarity={chunk.similarity:.2f}"
            )
            context_parts.append(f"{header}\n{chunk.content}")

        context_block = (
            "\n\n---\n\n".join(context_parts)
            if context_parts
            else "No matching data found in the AgWeatherNet database for this query."
        )

        # Build history block (FR-29 follow-up context)
        trimmed = history[-MAX_HISTORY_TURNS:]
        history_block = (
            "\n".join(f"{m['role'].upper()}: {m['content']}" for m in trimmed)
            or "(no prior conversation)"
        )

        system = ANSWER_SYSTEM.format(
            context=context_block,
            history=history_block,
            max_turns=MAX_HISTORY_TURNS,
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages += trimmed
        messages.append({"role": "user", "content": user_query})

        return self.chat.complete(messages=messages)


# UTILITIES


def _parse_json(text: str) -> dict:
    """Strip optional markdown code fences then parse JSON.

    Raises json.JSONDecodeError if the result is not valid JSON.
    """
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    return json.loads(cleaned)
