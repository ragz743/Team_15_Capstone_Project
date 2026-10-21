# AWN admin dashboard

An admin-only page for tracking the weather assistant's LLM cost, users, and query performance.
It is served at `/admin/` alongside the chat app and reads from `GET /api/admin/metrics`.

| Section | What it shows |
| --- | --- |
| Overview | LLM cost, LLM calls, cost per call, active users, cost per user, sessions per user, p95 response time, failed requests, each compared with the previous period |
| Cost and calls | Cost and calls (chat vs embedding) per day, and cost by model |
| Users and scale | Monthly active users, cost per user by month, and a projection of monthly cost at any number of monthly users |
| Query performance | Median and p95 response time, failed request rate, and requests by outcome |

Every chart has a table view, and the date range (7 days, 30 days, 90 days, 12 months) applies to the whole page.

## How the data is collected

The API records every `/api/chat` request in two Postgres tables (created automatically at startup, see
`backend/analytics/schema.sql`):

- `usage_requests`: one row per question with its user id, session id, response time, and outcome
- `usage_llm_calls`: one row per chat or embedding model call with its model, tokens, and cost

Chat model calls are captured with a LangChain callback, so any `_BaseChatbot` works without changes.
Embedding calls are captured by wrapping the embedding model in `MeteredEmbedding`. Embedding providers do not
report tokens, so embedding tokens are estimated (about 4 characters per token).

No question or answer text is stored. Recording never fails a chat request; errors are only logged.

### Users and sessions

The chat frontend identifies users and sessions by sending two optional headers with each `/api/chat` request:

| Header | Meaning | Format |
| --- | --- | --- |
| `X-AWN-User-Id` | anonymous id for the browser or account | 1-64 characters of `A-Z a-z 0-9 _ -` |
| `X-AWN-Session-Id` | id of the conversation | same |

Requests without a user id still count toward cost and calls, but not toward users, sessions, or cost per user.
The dashboard shows how many requests were unidentified.

### Cost

Cost = tokens × the price in [`backend/analytics/pricing.yaml`](../backend/analytics/pricing.yaml), saved when
each call is recorded. Models ending in `:free` cost $0. A model missing from the file is recorded at $0 and the
dashboard warns that cost is understated. **Add a price for any paid model before relying on the cost figures.**
Set `AWN_PRICING_FILE` to use a different file.

## Configuration (API environment)

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWN_ADMIN_TOKEN` | unset | Token admins enter to sign in. The dashboard is disabled until this is set. |
| `AWN_DASHBOARD_TIMEZONE` | `America/Los_Angeles` | Timezone used for days and months |
| `AWN_USAGE_TRACKING` | `true` | Set to `false` to stop recording usage |
| `AWN_PRICING_FILE` | bundled `pricing.yaml` | Alternative price table |

## Running locally

```sh
# API (from code_/, with the venv active and Postgres running)
AWN_ADMIN_TOKEN=change-me uvicorn backend.api:app --reload --port 8000

# dashboard (from code_/dashboard/)
npm install
npm run dev      # http://localhost:5174/admin/
npm test         # unit tests
```

To preview the dashboard without real traffic, add synthetic data (flagged and labelled "Includes demo data"):

```sh
python -m scripts.seed_dashboard_demo          # ~120 days of demo traffic
python -m scripts.seed_dashboard_demo --clear  # remove it again
```

With Docker, `docker compose up` builds the dashboard into the frontend container at http://localhost:8080/admin/.

## Assumptions waiting on the client

These were chosen as reasonable defaults and are easy to change once the client answers:

| Question | Current assumption | Where to change it |
| --- | --- | --- |
| How is a user identified? | Anonymous id sent by the chat app (`X-AWN-User-Id`) | `_client_id` in `backend/api.py` |
| What is a session? | One conversation (`X-AWN-Session-Id`) | same |
| Does "amount paid per user" mean our LLM cost per user? | Yes: LLM cost of identified users ÷ active users | `_summary` in `backend/analytics/usage_store.py` |
| What does cost include? | Chat and embedding model calls only, no hosting | `pricing.yaml` |
| What is "query performance"? | Response time (median, p95) and failure rate | `_SERIES_SQL` / `_SUMMARY_SQL` |
| How do admins sign in? | A shared token (`AWN_ADMIN_TOKEN`) | `require_admin` in `backend/analytics/admin_api.py` |
| Which timezone? | Pacific time | `AWN_DASHBOARD_TIMEZONE` |
