# AWN Backend

Backend code for the AWN chatbot demo. This includes the data loaders, vector
store, model wrappers, and the FastAPI server used by the React frontend.

## Chat API

The frontend talks to `backend/api.py`.

- `GET /api/health` checks whether the backend is ready.
- `POST /api/chat` sends the latest user question through `Retriever.retrieve()`.

Example chat request:

```json
{
  "messages": [
    { "role": "user", "content": "What's the frost risk in Prosser tonight?" }
  ]
}
```

Example response:

```json
{
  "reply": "assistant response",
  "model": "openai/gpt-oss-20b:free"
}
```

Right now the frontend can send the full conversation, but the backend only uses
the latest user message because `Retriever.retrieve()` takes one question string.

## Run Locally

From the repo root:

```bash
python -m pip install -e ".[dev]"
docker compose up -d pgvector
uvicorn backend.api:app --reload --port 8000
```

In another terminal:

```bash
cd code/frontend
npm install
npm run dev
```

Open `http://localhost:5173` and ask a question in the chat UI.

The frontend sends `/api` requests through the Vite proxy to FastAPI on
`http://localhost:8000`.

## Environment

Set these before starting FastAPI:

```bash
OPENROUTER_API_KEY=
OPENROUTER_EMBEDDING_MODEL=
PG_USER=
PG_PASSWORD=
```

Optional:

```bash
OPENROUTER_CHAT_MODEL=openai/gpt-oss-20b:free
OPENROUTER_CHAT_TEMPERATURE=0
```

`api.py` loads `.env` automatically if one exists.

## Check Retrieval Data

The web flow can run with an empty `daily_index`, but the assistant may not have
enough context to answer weather questions.

To check the table:

```bash
docker compose exec pgvector psql -U "$PG_USER" -d vectorstore \
  -c "SELECT count(*) FROM daily_index;"
```

If the count is `0`, run the project indexing flow or ask the retrieval/data
owner for the current setup.

## Smoke Test

```bash
curl http://localhost:8000/api/health

curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```
