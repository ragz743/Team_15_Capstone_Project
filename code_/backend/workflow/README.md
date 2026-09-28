# Natural Language to SQL Workflow w/ Langgraph

## What is Langgraph?
- langgraph is a popular framework for organizing a workflow as a graph, where each specific task can be though of as a node and the program passes data from one node to the next to complete the tasks. This abstraction can simplify complex programs and is often used with LLMs to separate context by task. Below is a high level overview of how this workflow operates in order to answer user questions.

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
- Weather query nodes retry SQL generation/execution up to three times when the database raises a programming error. This is adjusted with a global constant.
