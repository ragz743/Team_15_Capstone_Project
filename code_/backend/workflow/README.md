# Natural Language to SQL Workflow w/ Langgraph

## What is Langgraph?
- langgraph is a popular framework for organizing a workflow as a graph, where each specific task can be thought of as a node and the program passes data from one node to the next to complete the tasks. This abstraction can simplify complex programs and is often used with LLMs to separate context by task. Below is a high level overview of how this workflow operates in order to answer user questions.

## Workflow Overview

```mermaid
flowchart TD
	A([START]) --> B["run()"]
	B --> C["Find nearest station"]
	C --> D["_query_classifier<br/>split input into standalone sub-queries<br/>and classify each one"]
	D --> E{"_route_query<br/>dispatch one task per sub-query"}

	E -->|current_weather| F["_query_current<br/>generate, validate, and run SQL"]
	E -->|forecast_weather| G["_query_forecast<br/>generate, validate, and run SQL"]
	E -->|historical_weather| H["_query_historical<br/>generate, validate, and run SQL"]
	E -->|miscellaneous| I["_query_miscellaneous<br/>answer without a weather DB query"]

	F --> J["_chatbot_summarize<br/>combine task context into a single answer for LLM to consume"]
	G --> J
	H --> J
	I --> J
	J --> K([END])

	classDef setup fill:#f3f4f6,stroke:#6b7280,color:#111827;
	classDef llm fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
	classDef query fill:#dcfce7,stroke:#16a34a,color:#14532d;
	class B,C setup;
	class D,I,J llm;
	class F,G,H query;
```
### Notes
- The nearest-station lookup is shown as a separate step for clarity, though it is performed inside `run()` before the graph is invoked.
- The classifier can produce multiple sub-queries; `_route_query` dispatches a task for each, so multiple query branches may run for one user input before converging at the summarizer.
- Weather query nodes retry SQL generation/execution up to three times when the database raises a programming error. This is adjusted with a class variable.

## Web integration

FastAPI constructs `LangGraphEngine` at startup using the configured OpenRouter clients. Weather requests use this adapter exclusively. The standalone vector retrieval scripts remain available but the web service has no vector fallback.

The existing map picker resolves a point to an active Washington station. A prepared turn stores that station, its accepted reference time and up to six recent exchanges. Each answer creates a fresh `ChatbotWorkflow` and closes its source connections when finished. The classifier determines the weather categories and dates before query nodes ask the model to generate SQL.

Generated queries must pass the SQL AST policy before execution. The policy allows a single SELECT against the selected station table, permits only public weather columns and caps results at 200 rows. Source connections start read only with a statement timeout. PostgreSQL continues to store conversations separately.

Set `OPENROUTER_API_KEY`, `AWN_DB_HOST`, `AWN_DB_USER` and `AWN_DB_PASSWORD` in the local environment. `OPENROUTER_WORKFLOW_MODEL` defaults to `OPENROUTER_CHAT_MODEL`; `OPENROUTER_CLASSIFIER_MODEL` defaults to the workflow model. The web weather service does not require an embedding model or a populated vector index.

Saved requests default to `mode: weather`. This path supplies recent conversation context directly to the graph without invoking the saved history classifier. Selecting Past conversations sends `mode: history` and searches only that browser's saved conversations. History mode cannot execute new weather queries. Retries keep the original operation, selected point and acceptance time.

Malformed classifier JSON receives one schema repair attempt with the original inputs. Repeated invalid output produces an interpretation error. Provider failures do not enter the repair loop. SQL validation still runs independently before any source query executes.
