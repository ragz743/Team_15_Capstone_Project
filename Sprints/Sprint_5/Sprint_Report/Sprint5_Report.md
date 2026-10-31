# Sprint 5 Report (Dates from September 30, 2026 to October 31, 2026)

## YouTube link of Sprint 5
- [Sprint 5](https://www.youtube.com/watch?v=4gORS3hwsO8)

## What's New (User Facing)
* The chatbot interface was rebuilt with Material UI (MUI) to match the AgWeatherNet website, with a compact chat widget and an expanded view, and was shown working inside a local preview of the AWN site
* The chat is connected end to end to the LangGraph workflow, so every weather question is answered by querying the AgWeatherNet database directly instead of using vector search
* Users choose a weather station from a searchable station browser (by name, county, or distance from their location), and each answer is matched to the requested station and date
* Saved conversations: users can reopen and search past chats, and the selected station is restored with the conversation
* Answers are streamed as they are generated, and the sources behind each answer (station, dates, and measurements) can be expanded
* Average response time dropped from about 37 seconds to about 11 seconds across the sample question suite
* New LLM usage dashboard for AgWeatherNet administrators, showing active users, sessions, cost per user, retrieval quality, spending against the $50 monthly budget, and response times against the 5-second target

## Work Summary (Developer Facing)
The goal of Sprint 5 was to start deployment and strengthen the features built in Sprint 4. This meant adapting the chatbot interface to the existing AWN frontend, improving responsiveness, making the system more reliable through integration testing and fixes, and connecting chatbot activity to usage and cost reporting. The client gave the team AWS access and the AWN frontend and backend repositories on CodeCommit. After comparing costs and speed, the team chose the LangGraph architecture over the vector store. The client also added a new piece of scope: a dashboard tracking LLM costs, usage, and performance.
Developer-facing improvements include:
* Profiled the LangGraph backend to find bottlenecks, then converted the workflow to async nodes, added table schema caching, and streamed the final summary step, which together cut the average response time from about 37 seconds to about 11 seconds
* Replaced regex SQL validation with the SQLGlot parser: each generated query must be a single read-only SELECT on the selected station's table, using only that table's columns and approved functions
* Enforced query limits and timeouts: a 200-row limit, an 8-second statement timeout, a 366-day cap on historical ranges, and a maximum number of SQL retries so the model cannot query indefinitely
* Merged the work carried over from Sprint 4: station and date matching (#89), saved conversations (#90), the LangGraph chat connection (#98), and increased test coverage (#96, #102), resolving the interface mismatches between them and adding regression tests
* Added a chatbot response time test suite that logs performance for each question (#104)
* Built AI guardrails in layers: input checks for empty or oversized requests and patterns linked to prompt attacks or data extraction, structured classification that routes only weather questions to query handlers, SQL validation before execution, a check of the generated answer before it is streamed, and debug logs limited to workflow metadata rather than user text or station data
* Built the LLM usage dashboard (#110): a LangChain callback records every chat request with its user, login session, tokens, cost, response time, and outcome, and a daily quality check runs a fixed set of sample questions through the LangGraph workflow. The dashboard is being ported into the AWN frontend and backend repositories
* Moved configuration to environment variables for production (#82)

## Unfinished Work
The team moved from separate features toward one connected application tested through the user interface, and connected a local preview of the AWN frontend to the capstone backend. Production deployment to AWN's AWS environment is still pending, as are AWN authentication and the final porting of the chatbot and dashboard into the AWN repositories. The following items were still in review at the end of the sprint and will carry over to Sprint 6:
* LLM usage dashboard (#103, PR #110)
* AI chatbot guardrails (#71)

The dashboard also depends on items from the client: write access to the four dashboard tables on the live AWN database, a test admin account, and email settings for the monthly budget alert.

## Completed Issues/User Stories
Here are links to the issues that we completed in this sprint:

* [#32 Extend _BaseEmbedding and _BaseChatbot to be compatible with llama-cpp and ollama local models](https://github.com/ragz743/Team_15_Capstone_Project/issues/32)
* [#58 Backend + Frontend chatbot integration](https://github.com/ragz743/Team_15_Capstone_Project/issues/58)
* [#59 Return a clear no-data response without calling the chatbot when retrieval is empty](https://github.com/ragz743/Team_15_Capstone_Project/issues/59)
* [#60 Retrieve weather data for the requested station and date with station identity preserved](https://github.com/ragz743/Team_15_Capstone_Project/issues/60)
* [#67 Save and reference past conversations](https://github.com/ragz743/Team_15_Capstone_Project/issues/67)
* [#68 Retain context across conversation turns](https://github.com/ragz743/Team_15_Capstone_Project/issues/68)
* [#72 User Interactive Weather Station Selection](https://github.com/ragz743/Team_15_Capstone_Project/issues/72)
* [#73 Enable Complex Weather Queries](https://github.com/ragz743/Team_15_Capstone_Project/issues/73)
* [#75 Enforce Query Limits and Timeouts](https://github.com/ragz743/Team_15_Capstone_Project/issues/75)
* [#77 Chatbot response time test suite](https://github.com/ragz743/Team_15_Capstone_Project/issues/77)
* [#82 Enable environment based configuration for production](https://github.com/ragz743/Team_15_Capstone_Project/issues/82)
* [#108 Langgraph Performance Improvements](https://github.com/ragz743/Team_15_Capstone_Project/issues/108)

## Incomplete Issues/User Stories
Here are links to issues we worked on but did not complete in this sprint:

* [#103 LLM Metrics Dashboard](https://github.com/ragz743/Team_15_Capstone_Project/issues/103)
    - Implemented and in review (PR #110); being ported into the AWN repositories, waiting on database write access from the client
* [#71 Create AI Chatbot Guardrails](https://github.com/ragz743/Team_15_Capstone_Project/issues/71)
    - Implemented and in review
* [#76 Chatbot Response Accuracy Test Suite](https://github.com/ragz743/Team_15_Capstone_Project/issues/76)
    - Test coverage was increased in #96 and #102; the accuracy test suite itself is still open
* [#45 CI Pipeline with Github Actions](https://github.com/ragz743/Team_15_Capstone_Project/issues/45)
    - Carried over from Sprint 4; not started this sprint
* [#70 Require users to be signed in to access service](https://github.com/ragz743/Team_15_Capstone_Project/issues/70)
    - The client confirmed the chatbot is limited to logged-in users; this will be handled by connecting AWN authentication during deployment
* [#78 Deploy System to Production](https://github.com/ragz743/Team_15_Capstone_Project/issues/78)
    - Started: the team has AWS access and the AWN repositories, and a local AWN preview is connected to our backend
* [#79 Production Deployment Tear Down Automation](https://github.com/ragz743/Team_15_Capstone_Project/issues/79)
    - Planned for Sprint 6

## Code Files for Review
Please review the following code files, which were actively developed during this sprint, for quality:

* [workflow.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/workflow/workflow.py)
* [engine.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/workflow/engine.py)
* [sql_policy.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/workflow/sql_policy.py)
* [api.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/backend/api.py)
* [ChatWorkspace.tsx](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/frontend/src/components/ChatWorkspace.tsx)
* [ConversationSidebar.tsx](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/frontend/src/components/ConversationSidebar.tsx)
* [LocationPicker.tsx](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code_/frontend/src/components/LocationPicker.tsx)
* [usage_store.py (dashboard branch)](https://github.com/ragz743/Team_15_Capstone_Project/blob/dashboard/code_/backend/analytics/usage_store.py)
* [metering.py (dashboard branch)](https://github.com/ragz743/Team_15_Capstone_Project/blob/dashboard/code_/backend/analytics/metering.py)
* [Dashboard.tsx (dashboard branch)](https://github.com/ragz743/Team_15_Capstone_Project/blob/dashboard/code_/dashboard/src/components/Dashboard.tsx)
* [testing/backend folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/testing/backend)

## Retrospective Summary

### Here's what went well:
* Started porting the chatbot and dashboard into the AWN production environment
* Delivered many features and improvements, including a large cut in response time
* The pull requests carried over from Sprint 4 were reviewed and merged
* Client feedback on the project's direction was positive

### Here's what we'd like to improve:
* Pull requests stayed open for a long time
* Very large pull requests slowed down code review
* Changes across the workflow, frontend, saved conversations, and dashboard needed compatibility fixes when they were combined
* The new dashboard scope added work partway through the sprint

### Here are the changes we plan to implement in the next sprint:
* Communicate more often about pending reviews
* Complete the final porting to the AWN production environment and connect AWN authentication
* Verify the chatbot and dashboard end to end inside AWN
* Write the project documentation: installation, architecture, and design
