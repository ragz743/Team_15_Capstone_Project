# AWN Backend

Python backend: data loaders, vector store, LLM wrappers, and a FastAPI HTTP
layer that the React frontend talks to.

## Prototype chat API (Sprint 2)

`backend/api.py` exposes a minimal HTTP surface used by the frontend:

| Method | Path          | Purpose                                      |
| ------ | ------------- | -------------------------------------------- |
| GET    | `/api/health` | Readiness + chatbot status                   |
| POST   | `/api/chat`   | Forward a conversation to the LLM, get reply |

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

RAG is intentionally NOT wired here yet — it will be enabled once
`PgVectorStore.similarity_search` is implemented. At that point, swap the
direct `ChatbotOpenRouter.invoke` call in `api.py` for `Retriever.retrieve`.

## Running locally

From the repo root, with the project venv active:

```bash
# one-time: install deps (picks up fastapi + uvicorn)
python -m pip install -e ".[dev]"

# ensure SECRET_STUFF.env has OPENROUTER_API_KEY=...
# then start the server
uvicorn backend.api:app --reload --port 8000
```

Quick smoke test:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

## Configuration

Env vars consumed by `api.py` (all read from `.env` / `SECRET_STUFF.env`):

| Variable                      | Required | Default                    |
| ----------------------------- | -------- | -------------------------- |
| `OPENROUTER_API_KEY`          | yes      | —                          |
| `OPENROUTER_CHAT_MODEL`       | no       | `openai/gpt-oss-20b:free` |
| `OPENROUTER_CHAT_TEMPERATURE` | no       | `0`                       |

> OpenRouter rotates free-tier availability. If the default 404s, list live
> models with:
> ```bash
> curl -s "https://openrouter.ai/api/v1/models" \
>   -H "Authorization: Bearer $OPENROUTER_API_KEY" \
>   | jq -r '.data[] | select(.id | endswith(":free")) | .id'
> ```
> Then set `OPENROUTER_CHAT_MODEL=<id>` in `SECRET_STUFF.env`.
