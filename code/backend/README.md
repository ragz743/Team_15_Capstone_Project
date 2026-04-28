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

Try a question like:

```text
what was the average temperature in Whitman county recently?
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
uvicorn backend.api:app --reload --port 8000
```

In another terminal:

```bash
cd code/frontend
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
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

Example response:

```json
{
  "reply": "assistant response",
  "model": "openai/gpt-oss-20b:free"
}
```

The API accepts a message list from the frontend, but today it only sends the
latest user message to `Retriever.retrieve()`.

## Configuration

`backend/api.py` loads `.env` automatically.

| Variable | Required | Default |
| -------- | -------- | ------- |
| `OPENROUTER_API_KEY` | yes | none |
| `OPENROUTER_EMBEDDING_MODEL` | yes | `openai/text-embedding-3-small` in `.env.example` |
| `OPENROUTER_CHAT_MODEL` | no | `openai/gpt-oss-20b:free` |
| `OPENROUTER_CHAT_TEMPERATURE` | no | `0` |
| `PG_USER` | yes | none |
| `PG_PASSWORD` | yes | none |
| `PG_HOST` | no | `localhost` |
| `PG_PORT` | no | `5432` |

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
