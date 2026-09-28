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

Choose a point on the map, then try a question like:

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

The API passes the latest question and preceding user/assistant messages to the
weather interpreter. The browser chooses a map point; station filters are no longer
accepted. The server selects its nearby indexed source and validates the model's
structured dates before retrieval. The model can also ask for clarification or decline
an unrelated request.

The source catalog is cached for five minutes. Sources must have consistent Washington
coordinates and be within 50 km of the requested point. Set `radius_km` on
`StationCatalog` to adjust that limit. Missing records do not cause a switch to another
source. The first lookup and expired cache refreshes still read indexed station metadata.

The API continues to use `Retriever`. `ChatbotWorkflow` queries the AWN databases
directly and requires county input and session handling. Connecting it to the API is
a separate integration change.

For an existing database, apply `deployment/migrations/001_station_search_indexes.sql`
when deploying the updated backend. Fresh databases receive these indexes from the seed.
The CLI uses the same selection flow:

```bash
retrieve --latitude 46.73 --longitude -117.18 "Temperature here yesterday?"
```

## Configuration

`backend/api.py` loads `.env` automatically.

| Variable | Required | Default |
| -------- | -------- | ------- |
| `OPENROUTER_API_KEY` | yes | none |
| `OPENROUTER_EMBEDDING_MODEL` | yes | `openai/text-embedding-3-small` in `.env.example` |
| `OPENROUTER_CHAT_MODEL` | no | `openrouter/free` |
| `OPENROUTER_CHAT_TEMPERATURE` | no | `0` |
| `PG_USER` | yes | none |
| `PG_PASSWORD` | yes | none |
| `PG_HOST` | no | `localhost` |
| `PG_PORT` | no | `5432` |
| `AWN_DB_USER` | data loaders only | none |
| `AWN_DB_PASSWORD` | data loaders only | none |
| `AWN_DB_HOST` | data loaders only | none |

Missing or blank chat settings use `openrouter/free`. An explicit setting takes
precedence. If an existing `.env` still uses `openai/gpt-oss-20b:free`, replace that
value with `openrouter/free`; the old free endpoint is unavailable. The
[free router](https://openrouter.ai/docs/guides/routing/routers/free-router) selects
an available free model, so response quality and latency can vary between requests.

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
