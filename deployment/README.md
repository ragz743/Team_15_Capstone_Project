# Running with Docker

## Requirements
- Docker desktop is installed
- You have a working internet connection
- `.env` file stored in project root directory
- `.env` file contains deployment args described here:
    - `PG_USER`: the pgvector username
    - `PG_PASSWORD`: the pgvector password
    - `EMBEDDING_MODEL`: the embedding llm model file path
    - `CHATBOT_MODEL`: the chatbot llm model file path
- There is a `models/` directory containing `.gguf` model files matching `.env` args
    - `EMBEDDING_MODEL`: the llama.cpp compatible (gguf) model file for embedding
    - `CHATBOT_MODEL`: the llama.cpp compatible (gguf) model file for chatting

## Installation with Docker Compose
- Installation is handled completely by the `docker-compose.yml`, simply run `docker compose up -d` from the terminal to launch services in detached mode
- at any time, active docker containers can be seen with the command `docker ps`

## Shutting down services
- shutting down containers is also handled by `docker-compose.yml`, use command `docker compose down` to shutdown all docker compose containers.
