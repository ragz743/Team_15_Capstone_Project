# AWN Backend

This folder contains the backend for the AWN chatbot. It includes the data
loaders, pgvector search code, OpenRouter model wrappers, and the FastAPI server
used by the React frontend.

## Run The Demo With Docker

This is the easiest way to run the demo.

From the repo root:

```bash
cp .env.example .env
```

Add the private demo OpenRouter key to `.env`:

```bash
OPENROUTER_API_KEY=your-demo-key-here
```

Then start everything:

```bash
docker compose up
```

Open:

```text
http://localhost:8080
```

Choose a point on the map, then try:

```text
What was the temperature here yesterday?
```

The Docker setup starts three services:

| Service | Purpose |
| ------- | ------- |
| `frontend` | Serves the React app through nginx |
| `api` | Runs the FastAPI backend |
| `pgvector` | Runs Postgres with the pgvector extension |

The frontend calls `/api/*`, and nginx forwards those requests to FastAPI.
FastAPI connects to Postgres using `PG_HOST=pgvector` inside Docker.

This PR only starts the web stack. It does not create or refresh retrieval
data. The retrieval/data owner must make sure `daily_index` has data before a
demo that depends on real retrieved context.

## API Key Plan

For the client demo, the team will provide an OpenRouter key privately. Add that
key to `.env` as `OPENROUTER_API_KEY`. Rotate the key after the demo.

The checked-in `.env.example` already includes the default chat model and
embedding model.

## Local Development

Docker is the supported demo path. The local flow is still useful for backend
and frontend development.

From the repo root, with the virtual environment active:

```bash
python -m pip install -e ".[dev]"
docker compose up -d pgvector
index
python -m scripts.migrate_conversations
uvicorn backend.api:app --reload --port 8000
```

In another terminal:

```bash
cd code_/frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The Vite dev server forwards `/api/*` requests to FastAPI on port `8000`.

## API Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/api/health` | Checks whether the API, retriever, and chatbot are ready |
| `POST` | `/api/chat` | Sends the latest user question through retrieval and the chatbot |

Example request:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Temperature here yesterday?"}],"point":{"latitude":46.73,"longitude":-117.18}}'
```

Example response:

```json
{
  "reply": "assistant response",
  "model": "openrouter/free"
}
```

The API accepts a message list from the frontend, but today it only sends the
latest user message and preceding conversation to `Retriever.retrieve()`.
Weather requests include a user chosen `point` with numeric `latitude` and `longitude`.
The public station filter has been removed.

## Configuration

`backend/api.py` loads `.env` automatically.

| Variable | Required | Default |
| -------- | -------- | ------- |
| `OPENROUTER_API_KEY` | yes | none |
| `OPENROUTER_EMBEDDING_MODEL` | yes | `openai/text-embedding-3-small` in `.env.example` |
| `OPENROUTER_CHAT_MODEL` | no | `openrouter/free` |
| `OPENROUTER_HISTORY_MODEL` | no | inherits `OPENROUTER_CHAT_MODEL` |
| `OPENROUTER_CHAT_TEMPERATURE` | no | `0` |
| `PG_USER` | yes | none |
| `PG_PASSWORD` | yes | none |
| `PG_HOST` | no | `localhost` |
| `PG_PORT` | no | `5432` |
| `AWN_DB_USER` | data loaders only | none |
| `AWN_DB_PASSWORD` | data loaders only | none |
| `AWN_DB_HOST` | data loaders only | none |

Outside Docker, Postgres still defaults to `localhost:5432`.

## Quick Checks

Check API readiness:

```bash
curl http://localhost:8000/api/health
```

Check that retrieval data exists:

```bash
docker compose exec pgvector psql -U "$PG_USER" -d vectorstore \
  -c "SELECT count(*) FROM daily_index;"
```

The count must be greater than `0` for retrieval-based answers. If it is `0`,
the web stack can still run, but the chatbot will not have enough context to
answer weather questions well. Loading that data is outside this containerization
ticket.

## Saved conversations and map selection

Saved turns accept `conversation_id`, `request_id`, `message` and an optional `point`.
The server owns conversation context. Each request freezes its chosen point and resolved
query before answering. A retry uses the same message, point and request ID.
Existing conversations remain readable. A conversation saved before map selection
requires a point for a new weather question.

`SavedChatService` coordinates acceptance, preparation, answering and persistence.
`HistoryService` owns saved chat classification, lookup, context reuse and answers from
saved excerpts. `WeatherInterpreter` supplies validated weather dates and intent.

The API continues to use `Retriever`. LangGraph integration is a separate change that
will own weather classification and question splitting. It must use a session per
conversation and preserve frozen inputs on retries before replacing the current weather path.

Conversation reloads read context and messages from one database snapshot. A reply
completed during a reload cannot pair new messages with an old map point.

`StationCatalog` refreshes station metadata after five minutes and searches a latitude
band for the nearest source within 50 km. This distance is a product default to review.
Weather queries filter the selected source and dates before ranking. Private station
coordinates remain on the server. A missing match asks the user to choose another point.
