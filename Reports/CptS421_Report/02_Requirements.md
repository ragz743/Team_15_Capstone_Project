
# Functional Requirements
## Interactive AI Chatbot Window UI
### Table 15: FR-1: AI Chatbot Interactive UI Input Box
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI chatbot must support an input textbox in which users can input text that will be forwarded to the AI model for evaluation | Jaitun Patel is the primary client for this functionality, the chatbot UI | 0 |


### Table 16: FR-2: AI Chatbot and User Response History
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI chatbot UI must support a short history of responses so that users may reference previous queries | Client (Jaitun Patel) and end users (Growers/Extension Agents/Researchers) need a conversation context for usability | 0 |


### Table 17: FR-3: AI Chatbot UI limited accessibility
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI chatbot UI must only be accessible when users are authenticated through the AgWeatherNet web portal | Jaitun Patel | 0 |


## AI/LLM Model for Processing Queries
### Table 18: FR-4: AI model queries from natural language
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must support an AI/LLM model which can answer user queries related to AgWeatherNet’s weather data when prompted with natural language | Primary stakeholder need (Growers/Extension Agents/Researchers) to access AgWeatherNet data without SQL knowledge | 0 |


### Table 19: FR-5: AI Guardrails
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI model must cut short responses unrelated to AgWeatherNet’s dataset, including weather of regions outside of the supported weather stations or queries unrelated to weather in general | Source: Client requirement to keep the chatbot domain-focused and prevent misuse/out-of-scope responses | 0 |


### Table 20: FR-6: AI Interactive Weather Station Selection
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI system must confirm which weather station is most relevant to users before querying data (either through asking or suggesting nearest station from another location) | Jaitun Patel and System Administrators | 0 |


## AI Database integration
### Table 21: FR-7: AI Responses for live data queries
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI/LLM model must be able to answer questions related to current weather conditions for supported weather stations when prompted | Growers and Extension Agents need near-real-time station conditions for operational decisions | 0 |


### Table 22: FR-8: AI responses for historical data queries
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI model must be able to answer questions related to historical weather conditions for supported weather stations when prompted | Researchers and Extension Agents need historical station data for analysis and advisory work | 0 |


### Table 23: FR-9: AI responses for forecast data queries
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI model must be able to answer questions related to forecast weather conditions for supported stations over an approved forecast window (e.g., next 24-72 hours). | Growers and Extension Agents need near-future outlooks to plan irrigation, spraying, and labor | 0 |


### Table 24: FR-10: AI responses for aggregate data queries
| Description | Source | Priority |
| :--: | :--: | :--: |
| The AI model must support basic aggregation operations (sum/total, average, count of, minimum, maximum) over a range of data when prompted | Stakeholders need summary statistics (avg/min/max/totals) without manual dashboard work | 0 |


### Table 25: FR-11: Station Disambiguation
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must resolve user-provided station names to official AgWeatherNet station identifiers and ask for clarification when multiple stations match. | Stakeholders need reliable station selection; the client wants consistent station naming across the portal. | 0 |


### Table 26: FR-12: Read-only SQL enforcement
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must enforce that generated SQL is read-only (SELECT only) and must block destructive statements (INSERT/UPDATE/DELETE/DROP/ALTER). | Client security and data integrity requirements. | 0 |


### Table 27: FR-13: Query limits and timeouts
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must apply limits (row limits and maximum date-range guidance) and query timeouts to protect the database from expensive requests. | Client operations and performance requirements to keep the database responsive. | 0 |

## AI query testing suite
### Table 28: FR-14: Test suite for AI model query accuracy
| Description | Source | Priority |
| :--: | :--: | :--: |
| The team must provide automated testing to measure the accuracy of AI-generated responses given a specific input prompt | Client and future maintainers need automated validation that the chatbot returns correct results for representative prompts | 0 |


### Table 29: FR-15: Test suite for AI model response time
| Description | Source | Priority |
| :--: | :--: | :--: |
| The team must provide automated testing, measuring the response times of AI-generated responses given a specific input prompt | Client requires responsiveness for a usable portal experience; developers need measurable performance targets | 0 |

## AWS EC2 Deployment
### Table 30: FR-16: System deployment
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must be able to be deployed to an AWS EC2 instance while maintaining all of its functionality | Client infrastructure requirements to run the chatbot service on AgWeatherNet’s AWS EC2 environment | 0 |


### Table 31: FR-17: System tear down
| Description | Source | Priority |
| :--: | :--: | :--: |
| The system must gracefully shut down when directed by administrators | System administrators require a safe shutdown procedure for maintenance and incident response | 0 |


### Table 32: FR-18: Environment-based configuration
| Description | Source | Priority |
| :--: | :--: | :--: |
| The deployment must support configuration through environment variables or a secure configuration mechanism (DB host, credentials, model settings) without hardcoding secrets in code. | Client security and maintainability requirements. | 0 |


## Project Documentation
### Table 33: FR-19: Project installation documentation
| Description | Source | Priority |
| :--: | :--: | :--: |
| The project must be delivered with documentation which describes how to build and run the application, including dependency installation with versioning | Future developers and administrators need clear setup instructions for repeatable builds and execution | 0 |


### Table 34: FR-20: Project architecture documentation
| Description | Source | Priority |
| :--: | :--: | :--: |
| The project must be delivered with documentation which describes all of the high-level components of the system and their responsibilities | Client and future maintainers need a high-level component map and request flow for long-term maintenance | 0 |


# Non-Functional Requirements
## Table 35: Non-Functional Requirements
| Non-Functional Requirement | Description |
| :--: | :--: |
| NFR-1: Performance| The system shall return responses to user queries within an average of 5 seconds under normal operating conditions. |
| NFR-2: Accuracy and Data Integrity | The system shall return responses that are strictly grounded in AgWeatherNet data and must minimize the hallucination of weather data. |
| NFR-3: Availability | The system shall maintain at least 99% uptime during operational hours. |
| NFR-4: Scalability | The system shall support concurrent access by multiple users without significant degradation in response time. |
| NFR-5: Security | The system shall prevent unauthorized database access, protect against SQL injection, and ensure secure communication between components.
| NFR-6: Usability | The system interface shall be intuitive and require no prior technical knowledge of database systems. |
| NFR-7: Maintainability | The system shall utilize sound software design to optimize maintainability of the application with respect to modularity and code reuse. |


