# Sprint 23 Report (Dates from April 24th, 2026 to May 1st, 2026)

## YouTube link of Sprint 3
- [Sprint 3](https://youtu.be/6js8kwauWhU)
- [Client Demo](https://www.youtube.com/watch?v=sJ162NDnIm4)

## What's New (User Facing)
* Chatbot UI has been integrated with FastAPI Backend so it can make calls to LLM Api’s and answer questions
* Application is containerized with Docker, allowing the frontend to communicate with the backend using Nginx
* The recent chats feature has been added to the application, lightweight and ready to be improved in the future
* Document loader now stores embeddings into the pgvector database for later retrieval
* Indexed documents now capture more station data, this means more user queries can be answered!
* Retriever class has been added, which embeds user queries and returns relevant documents using similarity search
* Improvements to chatbot prompt templates, chatbot now understands it is a weather data assistant

## Work Summary (Developer Facing)
The goal of the final sprint of the semester was to create a prototype that would impress the client, this included creating the process of end-to-end flow of information from user query to chatbot response. To do this, the team finished components that had not been completed in previous sprints and polished components which were functioning but needed some improvements. As a result, most of the changes were user-facing. Some developer-facing improvements include:
* LLM Interface classes to support containerized LLMs
* New test cases for the retriever class
* Improvements to the vector database schema, which will constrain database size
* indexed documents are stored in markdown tables to easily integrate with LLMs

## Unfinished Work
Overall, the team picked a reasonable set of tasks to complete for the shortened sprint 3. Since the team prioritized user-facing functionality, some testing areas have not been fully completed. Such as robust testing of document loading, retrieved document relevancy, and front-end UI testing. These shortcomings have been discussed with the client during the prototype demo and are a primary focus of sprints in the upcoming semester. Other than testing, the only ticket not closed was a stretch goal of integrating currently used linters, formatters, and testing frameworks into a CI pipeline using GitHub Actions. This item was delayed so that more effort could be focused on the client demo.

## Completed Issues/User Stories
Here are links to the issues that we completed in this sprint:

* [#18 Integrate Embedding Modeland Vector DB](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=170152505&issue=ragz743%7CTeam_15_Capstone_Project%7C18)
* [#41 Vector Store Retrieval](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=180290745&issue=ragz743%7CTeam_15_Capstone_Project%7C41)
* [#46 Standup FastAPI web server to make front end accessible](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=180600376&issue=ragz743%7CTeam_15_Capstone_Project%7C46)
* [#47 Increase Document/Metadata information Pipeline](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=180602011&issue=ragz743%7CTeam_15_Capstone_Project%7C47)



 ## Incomplete Issues/User Stories
 Here are links to issues we worked on but did not complete in this sprint:

* [#45 CI Pipeline with Github Actions](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=180597529&issue=ragz743%7CTeam_15_Capstone_Project%7C45)
    - Not started, other tasks took priority over CI. Will be first in line next sprint!
 * [#48 Prompting Strategies and Testing Stage](https://github.com/users/ragz743/projects/4/views/1?pane=issue&itemId=181117492&issue=ragz743%7CTeam_15_Capstone_Project%7C48)
     - Partially implemented for client demo, but should be formalized and reviewed.
* [#54 Implementing Metadata Filtering](https://github.com/ragz743/Team_15_Capstone_Project/issues/54)

## Code Files for Review
Please review the following code files, which were actively developed during this sprint, for quality:


 * [retriever.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/retriever.py)
 * [vector_store.py](https://github.com/ragz743/Team_15_Capstone_Project/blob/main/code/backend/vector_store.py)
 * [databases folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/backend/databases)
 * [loaders folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/backend/loaders)
 * [frontend/src folder](https://github.com/ragz743/Team_15_Capstone_Project/tree/main/code/frontend/src)


## Retrospective Summary

### Here's what went well:
* Presentations for the client were well-prepared and effective
* Completed features demonstrate end-to-end system functionality
* We are caught up after the delayed start to the project!

### Here's what we'd like to improve:
* Task distribution needs improvement for better efficiency
* Provide more detailed information for Kanban tasks
* Improve testing, especially at the integration level between major components
* Limit size of features to keep flow of code consistent and code reviews small!


### Here are the changes we plan to implement in the next sprint:
* Improve current tests and add more tests, especially at the system and integration levels
* Hybridize the RAG pipeline to minimize expensive indexing operations
* Fully connect all of the components, creating a seamless experience
* Transition development environment to be ready for a production environment deployment on AWS
* Add different types of visuals to the UI (tables and plots)
