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
> Note: During development it is a common need to wipe the database for a clean start! To do this shutdown the containers and remove the current volumes with `docker compose down -v` **WHICH WILL DELETE ALL CONTAINER DATA SO USE CAUTION!!!**


## Shutting down services
- shutting down containers is also handled by `docker-compose.yml`, use command `docker compose down` to shutdown all docker compose containers.

## Using Docker profiles
- Users need to run different services depending on available hardware, as a result project llm models are able to be configured using `docker profiles` which allow services to be started/stopped conditionally by calling their group with the `--profile` flag.
- for example to run llm models locally using llama-cpp, docker compose should be called using the profiles flag: `docker compose --profile local_llm up` will launch both the embedding and chatbot models in local docker containers
- **Note: profiles must also be used for bringing down services!**
    - `docker compose --profile local_llm down` to bring down local model containers.
