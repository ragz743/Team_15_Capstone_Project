# Sprint 2 Report (Dates from March 26th, 2026 to April 24th, 2026)

## YouTube link of Sprint 2
Video Link: https://youtu.be/ltAWGXFPh8g

## What's New (User Facing)
 * Establish project infrastructure including Docker containerization, pgvector database setup, LLM containerization, environment variable management, and pytest configuration
 * Implement RAG pipeline components including document loading from AgWeatherNet and prompt-based retrieval for context-aware chatbot responses
 * Deliver a functional end-to-end prototype connecting the UI, language model, and AgWeatherNet data pipeline

## Work Summary (Developer Facing)
This sprint focused on turning a high-level system concept into a working, integrated prototype by building the foundation first and layering functionality on top. The team prioritized environment consistency and reproducibility, which led to setting up containerized services for the database, language model, and application, reducing setup issues across development environments. From there, efforts shifted to connecting components—specifically figuring out how to structure and retrieve AgWeatherNet data. The team iterated on data formatting, embedding strategies, and prompt structure.

## Unfinished Work
We planned to complete the full prototype during Sprint 2, but were unable to finish within the timeline. The remaining work is focused on finalizing the end-to-end prototype and improving the user interface, which we aim to complete in Sprint 3.

## Completed Issues/User Stories
Here are links to the issues that we completed in this sprint:

 * [#11 AgWetherNet Database Connection](https://github.com/ragz743/Team_15_Capstone_Project/issues/11)
 * [#12 Python Project Management](https://github.com/ragz743/Team_15_Capstone_Project/issues/12)
 * [#14 LLM Containerization](https://github.com/ragz743/Team_15_Capstone_Project/issues/14)
 * [#15 PostgreSQL + pgvector database setup script](https://github.com/ragz743/Team_15_Capstone_Project/issues/15)
 * [#16 Document Loading RAG Stage](https://github.com/ragz743/Team_15_Capstone_Project/issues/16)
 * [#19 Vector DB Queries](https://github.com/ragz743/Team_15_Capstone_Project/issues/19)
 * [#20 RAG Prompt Templates](https://github.com/ragz743/Team_15_Capstone_Project/issues/20)
 * [#21 Large Language Model Integration](https://github.com/ragz743/Team_15_Capstone_Project/issues/21)
 * [#22 Chatbot UI Mockup](https://github.com/ragz743/Team_15_Capstone_Project/issues/22)
 * [#23 Docker Compose Setup](https://github.com/ragz743/Team_15_Capstone_Project/issues/23)
 * [#24 PyTest Setup and Config](https://github.com/ragz743/Team_15_Capstone_Project/issues/24)
 * [#25 Environment Variable Management](https://github.com/ragz743/Team_15_Capstone_Project/issues/25)

 ## Incomplete Issues/User Stories
 Here are links to issues we worked on but did not complete in this sprint:

 * [#17 Document Splitting RAG Stage](https://github.com/ragz743/Team_15_Capstone_Project/issues/17) Implemented but ultimately determined to be unnecessary for the current prototype architecture.
 * [#18 Integrate Embedding Model and Store Vectors in Vector DB](https://github.com/ragz743/Team_15_Capstone_Project/issues/18) Currently in progress but was not completed within the sprint timeline.

## Code Files for Review
Please review the following code files, which were actively developed during this sprint, for quality:
 * [indexer.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/indexer.py)
 * [model_factory.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/model_factory.py)
 * [retriever.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/retriever.py)
 * [vector_store.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/vector_store.py)
 * [databases folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/backend/databases)
 * [loaders folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/backend/loaders)
 * [models folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/backend/models)

## Retrospective Summary
Here's what went well:
  * Presentations for the client were well-prepared and effective
  * Moved from initial concept to a defined system architecture
  * Advanced from planning to a functional prototype with UI
  * Improved clarity on technical direction and implementation strategy

Here's what we'd like to improve:
   * Task distribution needs improvement for better efficiency
   * Communication and coordination could be clearer to reduce duplicate work and ensure alignment across components


Here are changes we plan to implement in the next sprint:
   * Complete implementing the prototype
   * Refine chatbot UI for demo readiness and usability
