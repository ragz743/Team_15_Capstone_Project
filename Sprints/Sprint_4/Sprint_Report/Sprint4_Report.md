# Sprint 4 Report (Dates from August 24, 2026 to September 30, 2026)

## YouTube link of Sprint 4
- [Sprint 4](https://youtu.be/3viRa1xrhck)

## What's New (User Facing)
* Complete end-to-end functionality, all components of the chatbot are now integrated!
* The chatbot now searches all 3 indexes (historical, current, and forecast data) together, and combines the results into a single labeled context
* Users can filter weather data by station or county, filters are detected automatically from the question or passed directly through the API
* Redesigned the AgWeatherNet chat workspace with WSU branding, suggested weather questions, clearer messages, and desktop/mobile layouts
* Chat is more reliable, with input validation, readable service errors, rate-limit handling, and a clear response when no weather records match a question
* Weather records are matched to the requested station and date before ranking, and the records behind each answer are shown to the user
* Proof-of-concept Natural Language to SQL (NL2SQL) component built with LangGraph, which answers questions by querying the weather database directly instead of using vector search

## Work Summary (Developer Facing)
The goal of Sprint 4 was to complete at least 80% of the features, integrate the front and back end, explore an NL2SQL back end in place of RAG vector search, and catch up on testing. After discussing the design with the client in previous sprints, this sprint was focused on implementation so that we have a functioning product to iterate on and are ready for deployment work in Sprint 5. Feedback from the client at the end of Sprint 3 drove much of this work, including the pivot toward NL2SQL and making testing a priority. Developer-facing improvements include:
* LangGraph workflow modeled as a graph where each node handles a task, with SQL generation, retries, question rewording, and a simple API that takes a question and minimal location info (coordinates and county)
* Nearest station search given a coordinate, and a new Copilot chatbot class offering the same chatbot API with a Copilot backend
* Logging for the LangGraph workflow so we can see the internal thought process of the system
* Unit tests for multi-index search, context labeling, empty results, and metadata filtering
* Sample Question Test Suite with repeatable tests for chatbot response quality, using the client's sample questions
* API layer and RAG pipeline tests using fake retrievers
* E2E tests that send real questions to the live API with Docker running, including out-of-scope question refusal tests
* Data accuracy tests that compare numeric values in chatbot responses against database records to detect hallucinations
* Optional pytest argument for LLM tests, so they don't run by default and waste credits

## Unfinished Work
The team completed the core goal of the sprint, end-to-end functionality with all components integrated. As features grew more complex, PR diffs got larger, and some interfaces between components did not match up when it came time to merge. As a result, some of PRs are still open, which are:
* Matching weather records to station and date (#89)
* Saving and referencing past conversations (#90)
* Connecting the chat to the LangGraph workflow (#98)
* Increasing test coverage (#96)
Since these PRs have not finished being reviewed, they will be carried over to Sprint 5.

## Completed Issues/User Stories
Here are links to the issues that we completed in this sprint:

* [#54 Implementing Metadata Filtering](https://github.com/ragz743/Team_15_Capstone_Project/issues/54)
* [#56 Proof of Concept Natural Language to SQL Generation (Langgraph)](https://github.com/ragz743/Team_15_Capstone_Project/issues/56)
* [#57 Sample Question Test Suite](https://github.com/ragz743/Team_15_Capstone_Project/issues/57)
* [#61 Combine daily_index, live_index, and forecast_index in vector_store.py](https://github.com/ragz743/Team_15_Capstone_Project/issues/61)
* [#66 Data accuracy validation (DB value vs Chatbot response)](https://github.com/ragz743/Team_15_Capstone_Project/issues/66)
* [#74 Enforce Station Disambiguation](https://github.com/ragz743/Team_15_Capstone_Project/issues/74)
* [#83 UI Re-Design](https://github.com/ragz743/Team_15_Capstone_Project/issues/83)
* [#93 Copilot Chatbot Class](https://github.com/ragz743/Team_15_Capstone_Project/issues/93)
* [#94 Langgraph Logging](https://github.com/ragz743/Team_15_Capstone_Project/issues/94)

## Incomplete Issues/User Stories
Here are links to issues we worked on but did not complete in this sprint:

* [#58 Backend + Frontend chatbot integration](https://github.com/ragz743/Team_15_Capstone_Project/issues/58)
    - Chat error handling was merged in #88, connecting the chat to the LangGraph workflow is in review (#98)
* [#59 Return a clear no-data response without calling the chatbot when retrieval is empty](https://github.com/ragz743/Team_15_Capstone_Project/issues/59)
    - Fix merged in #88, needs to be verified and closed
* [#60 Retrieve weather data for the requested station and date with station identity preserved](https://github.com/ragz743/Team_15_Capstone_Project/issues/60)
    - Implemented, PR #89 is in review
* [#67 Save and reference past conversations](https://github.com/ragz743/Team_15_Capstone_Project/issues/67)
    - Implemented, PR #90 is in review and depends on #89
* [#68 Retain context across conversation turns](https://github.com/ragz743/Team_15_Capstone_Project/issues/68)
* [#76 Chatbot Response Accuracy Test Suite](https://github.com/ragz743/Team_15_Capstone_Project/issues/76)
    - Additional test cases in progress (#96)
* [#77 Chatbot response time test suite](https://github.com/ragz743/Team_15_Capstone_Project/issues/77)
* [#45 CI Pipeline with Github Actions](https://github.com/ragz743/Team_15_Capstone_Project/issues/45)
    - Carried over from Sprint 3, planned for Sprint 5
* [#70 Require users to be signed in to access service](https://github.com/ragz743/Team_15_Capstone_Project/issues/70)
    - Planned for Sprint 5, pending discussion with the client on whether to include authentication
* [#71 Create AI Chatbot Guardrails](https://github.com/ragz743/Team_15_Capstone_Project/issues/71)
    - Planned for Sprint 5
* [#73 Enable Complex Weather Queries](https://github.com/ragz743/Team_15_Capstone_Project/issues/73)
    - Planned for Sprint 5
* [#75 Enforce Query Limits and Timeouts](https://github.com/ragz743/Team_15_Capstone_Project/issues/75)
    - Planned for Sprint 5
* [#78 Deploy System to Production](https://github.com/ragz743/Team_15_Capstone_Project/issues/78)
    - Planned for Sprint 5
* [#79 Production Deployment Tear Down Automation](https://github.com/ragz743/Team_15_Capstone_Project/issues/79)
    - Planned for Sprint 5
* [#82 Enable environment based configuration for production](https://github.com/ragz743/Team_15_Capstone_Project/issues/82)
    - Planned for Sprint 5

## Code Files for Review
Please review the following code files, which were actively developed during this sprint, for quality:

* [workflow.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/workflow/workflow.py)
* [api.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/api.py)
* [retriever.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/retriever.py)
* [vector_store.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/vector_store.py)
* [chatbot_github_copilot.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/models/chatbot_github_copilot.py)
* [ChatWorkspace.tsx](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/frontend/components/ChatWorkspace.tsx)
* [testing/backend folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/testing/backend)
* [testing/e2e folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/testing/e2e)

## Retrospective Summary

### Here's what went well:
* Design plans from previous sprints paid off, making implementation straightforward
* Achieved full end-to-end functionality with all components integrated
* Good tests helped validate new features, saving time
* Client feedback guided key design decisions and priorities throughout the sprint

### Here's what we'd like to improve:
* Increasing feature complexity led to big PR diffs that were hard to review
* Some interfaces between components did not match up at merge time
* Several PRs were still in review at the end of the sprint

### Here are the changes we plan to implement in the next sprint:
* Scope Kanban items smaller to keep PRs and code reviews small
* Communicate early on design, not at PR time!
* Prepare for deployment, including integration with the AWN system and security
* Build on existing features, supporting complex queries and improving performance
* Continue making testing a priority
* Creating a CI pipeline with GitHub actions
* Discussing with client on whether to include authentication (i.e. login) to the chatbot
