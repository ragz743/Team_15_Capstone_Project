# AWN Backend

Python backend: data loaders, vector store, LLM wrappers, and a FastAPI HTTP
layer that the React frontend talks to.

## Prototype chat API (Sprint 2)

`backend/api.py` exposes a minimal HTTP surface used by the frontend:

| Method | Path          | Purpose                                      |
| ------ | ------------- | -------------------------------------------- |
| GET    | `/api/health` | Readiness + retriever/chatbot status         |
| POST   | `/api/chat`   | Send latest user question through retrieval  |

`POST /api/chat` request body:

```json
{
  "messages": [
    { "role": "user", "content": "What's the frost risk in Prosser tonight?" }
  ]
}
```

Response:

```json
{ "reply": "…assistant text…", "model": "google/gemma-2-9b-it:free" }
```

The API currently sends the latest user message into `Retriever.retrieve`.
Conversation history is still accepted from the frontend, but the retriever
interface only accepts one question string today.

## Run the demo

From the repo root, with the project venv active:

```bash
# one-time: install deps
python -m pip install -e ".[dev]"

# start pgvector
docker compose up -d pgvector

# seed daily_index before demoing real retrieved context
# this uses models.yaml for the embedding model configuration
index

# start FastAPI
uvicorn backend.api:app --reload --port 8000
```

In another terminal:

```bash
cd code/frontend
npm install
npm run dev
```

Open `http://localhost:5173`, enter a question, and the React app will call
FastAPI through the Vite `/api` proxy.

Quick smoke test:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

## Configuration

Env vars consumed by `api.py` and the pgvector connection. `api.py` loads
`.env` automatically; otherwise export these in the shell before starting
uvicorn:

| Variable                      | Required | Default                    |
| ----------------------------- | -------- | -------------------------- |
| `OPENROUTER_API_KEY`          | yes      | —                          |
| `OPENROUTER_EMBEDDING_MODEL`  | yes      | —                          |
| `OPENROUTER_CHAT_MODEL`       | no       | `openai/gpt-oss-20b:free` |
| `OPENROUTER_CHAT_TEMPERATURE` | no       | `0`                       |
| `PG_USER`                     | yes      | —                          |
| `PG_PASSWORD`                 | yes      | —                          |

> OpenRouter rotates free-tier availability. If the default 404s, list live
> models with:
> ```bash
> curl -s "https://openrouter.ai/api/v1/models" \
>   -H "Authorization: Bearer $OPENROUTER_API_KEY" \
>   | jq -r '.data[] | select(.id | endswith(":free")) | .id'
> ```
> Then set `OPENROUTER_CHAT_MODEL=<id>` in `.env` or export it in your shell.

Before demo, we need to confirm `daily_index` has rows:

```bash
docker compose exec pgvector psql -U "$PG_USER" -d vectorstore \
  -c "SELECT count(*) FROM daily_index;"
```

If `daily_index` is empty, the web flow still works, but the assistant may say
there is not enough context to answer.

Containerization handoff: this PR keeps localhost defaults, including
`PgVectorConnection host=localhost`. The follow-up containerization PR should
make that host env-driven so FastAPI can connect to `pgvector` inside the
compose network.
