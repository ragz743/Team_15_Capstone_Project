# AWN admin dashboard

An admin-only page for tracking the AgWeatherNet weather assistant's users, LLM spending, and
performance. It is served at `/admin/` alongside the chat app, which will run on an AWS EC2 instance, and
reads from the `/api/admin/*` endpoints.

| Section | What it shows |
| --- | --- |
| Overview | Active users, successful sessions, calls, share answered within 5 s, LLM spending, cost per 1,000 calls, failed calls; each compared with the previous period |
| Users and sessions | Active users and successful sessions per day, week, or month |
| Cost per user | Every logged-in user's calls, sessions, tokens, and spending: searchable, sortable, CSV export |
| Spending | Month-to-date spending against the $50 budget, spending and calls over time, spending by model |
| Query performance | Response time against the 5 s target, share answered within 5 s, failed calls, calls by outcome |

The page is built with **MUI (Material UI)**, like the AgWeatherNet website. All colors and shapes come from
[`src/theme.ts`](src/theme.ts) (WSU crimson); when the dashboard moves into the AWN website repo, swap in the site's
own MUI theme there. The charts are custom SVG (validated for colorblind safety) and take their colors from the
`--series-*` variables in `src/styles.css`.

The date range (7 days to 12 months) and the Daily / Weekly / Monthly grouping apply to the whole page. Every
chart has a table view, the page refreshes its data every hour, and **Export CSV** downloads the time series.

## Definitions (agreed with the client)

| Term | Definition |
| --- | --- |
| Active user | A signed-in user who asked the chatbot at least one question. Signing in is required to use the chatbot, so a call without a user ID is flagged as **unidentified** (a chat app problem): it counts toward spending but not users |
| Session | One login session (expires after 2 days), identified by its session ID |
| Successful session | A session in which every call was answered |
| Call | One attempt to answer a question. Each call can make several model requests; reopening a saved answer adds no usage |
| LLM spending | Real spending on model requests only (no hosting, no projections). OpenRouter's free models cost $0 |
| Response time target | Under 5 seconds, end to end |
| Budget | Email weather@wsu.edu once a month's real spending passes $50 |

## How the data is collected

The API records every `/api/chat` call in AgWeatherNet's `awn` MariaDB database, in tables AgWeatherNet
created (a copy of their definitions is in `backend/analytics/schema.sql`; the API does not create them):

- `table_llm_usage_requests`: one row per call with its user ID, login session ID, response time, and outcome
- `table_llm_usage_model_calls`: one row per model request with its model, tokens, and cost
- `table_llm_usage_budget_alerts`: one row per month once spending passes the budget, so the email goes out once

Chat model requests are captured with a LangChain callback, including the LangGraph classifier, query
generation, summarizer, and saved-history interpretation and answers. No question or answer text is stored
in the analytics tables. Recording failures do not fail the chat request.

Both chat payloads use the same tracker: the older `messages` payload and the saved-chat payload with
`conversation_id`, `request_id`, and `message`. A completed saved turn is replayed without recording another
call. A failed attempt that invokes a model is recorded; generating a new answer on retry is a new attempt
and its model usage is recorded separately. Merely reopening a conversation does not add usage.
Empty answers count as failed calls and are excluded from successful-answer response times.

The chatbot answers only through the LangGraph SQL workflow, so every recorded model request is a chat
model request. Model tokens and billed cost come from provider
metadata; token estimates are labelled. For a short overview of the design, see
[`backend/analytics/README.md`](../backend/analytics/README.md).

### Users and sessions

The chat app identifies the signed-in user by sending two headers with each `/api/chat` request:

| Header | Meaning |
| --- | --- |
| `X-AWN-User-Id` | the signed-in user's ID (always present, since signing in is required) |
| `X-AWN-Session-Id` | the login session ID |

Both accept 1-64 characters of `A-Z a-z 0-9 . _ @ -`. A session without a valid user is ignored.

The frontend reads the host's current identity before each regular or saved chat request:

```ts
window.AWN_CHAT_IDENTITY = {
  userId: signedInUser.username,
  sessionId: loginSession.analyticsId,
};
// On logout:
window.AWN_CHAT_IDENTITY = null;
```

Use a non-secret session identifier, never a login cookie, access token, or API key. These headers are
analytics labels, not authentication. In production, the authenticated AWN backend can instead overwrite
the headers on the chat proxy using its verified login context. This repository does not implement the
AWN website's login system. The browser's saved-history cookie and conversation IDs are not login identities.

Without host identity, real calls still contribute tokens, cost, latency, outcomes, and model totals, but
remain unidentified and do not inflate user or login-session counts. Identity changes apply to future
calls; they do not relabel historical usage.

### Connecting the committed chatbot

The integration combines the chatbot in [PR #98](https://github.com/ragz743/Team_15_Capstone_Project/pull/98)
(`feature/connect-langgraph`, `17b2bdc`) with this dashboard in
[PR #110](https://github.com/ragz743/Team_15_Capstone_Project/pull/110) (`dashboard`, `2b0d36c`).

Choose one usage destination:

- **This dashboard:** leave `AWN_BACKEND_URL` and `AWN_INTERNAL_KEY` empty, set `AWN_ADMIN_TOKEN`, and
  keep `AWN_USAGE_TRACKING=true`. Chat and `/api/admin/*` use the same PostgreSQL usage tables.
- **AWN website dashboard:** set both `AWN_BACKEND_URL` and `AWN_INTERNAL_KEY` on the Python API. The
  existing reporter sends each completed attempt to `/api/v1/internal/llm-usage/requests`. The Go backend
  must implement that endpoint and accept the same key. This mode replaces local `/api/admin/*` storage;
  it does not mirror reports into both dashboards. Do not put the internal key in frontend configuration.

To verify locally, configure the provider and databases in `.env`, apply the conversation migrations,
then start the API and the two frontends using the commands below. Submit a question in the chatbot,
refresh `/admin/`, and check that calls, model requests, tokens, and costs changed. Reopen the saved
conversation to confirm it does not add usage. Provider-reported free calls may legitimately cost $0.

No demo seed is required. If synthetic rows were previously seeded, the dashboard labels the mixed data
as "Includes demo data". `PYTHONPATH=code_ python testing/seed_dashboard_demo.py --clear` (from the
repository root) removes only those synthetic rows
when you are ready to view real traffic alone.

### Spending

Spending is the cost OpenRouter reports in each response
([usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)), so there is no
price list to keep up to date. Free models are reported as $0. A request whose provider reports no cost is
counted as $0 and the dashboard warns that spending may be understated.

### Budget alert

Every hour the API compares this month's real spending (demo data excluded) with the budget. Once it passes,
one email goes to the alert address; a failed send is retried hourly and shown on the dashboard. **The email is
only sent once SMTP is configured** (see below).

## Configuration (API environment)

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWN_USAGE_DB_USER`, `AWN_USAGE_DB_PASSWORD` | unset | MariaDB account (from AgWeatherNet) that can `SELECT, INSERT, UPDATE` the `table_llm_usage_*` tables. Kept separate from the chatbot's read only `AWN_DB_USER`. Usage tracking and the dashboard are off until set |
| `AWN_USAGE_DB_HOST`, `AWN_USAGE_DB_PORT`, `AWN_USAGE_DB_NAME` | `AWN_DB_HOST`, `3306`, `awn` | Where the usage tables are |
| `AWN_ADMIN_TOKEN` | unset | Placeholder login until the dashboard uses the AWN website's admin sign-in (see open items below): admins type this value to sign in. Any value works; the project `.env` uses a dummy one. The dashboard is disabled until this is set |
| `AWN_DASHBOARD_TIMEZONE` | `America/Los_Angeles` | Timezone for days, months, and the monthly budget |
| `AWN_RESPONSE_TARGET_MS` | `5000` | Response time target |
| `AWN_MONTHLY_BUDGET_USD` | `50` | Monthly spending that triggers the alert |
| `AWN_BUDGET_ALERT_EMAIL` | `weather@wsu.edu` | Alert recipients (comma separated) |
| `AWN_SMTP_HOST`, `AWN_SMTP_PORT`, `AWN_SMTP_USERNAME`, `AWN_SMTP_PASSWORD`, `AWN_SMTP_FROM`, `AWN_SMTP_STARTTLS` | unset, `587`, unset, unset, unset, `true` | Mail server for the budget alert. Optional: set `AWN_SMTP_HOST` and `AWN_SMTP_FROM` together, and `AWN_SMTP_USERNAME` and `AWN_SMTP_PASSWORD` together. These and the budget settings are checked when the API starts |
| `AWN_DASHBOARD_URL` | unset | Link included in the alert email |
| `AWN_USAGE_TRACKING` | `true` | Set to `false` to stop recording usage |
| `AWN_BACKEND_URL`, `AWN_INTERNAL_KEY` | unset | When both are set, usage is sent to the AgWeatherNet backend (awn_be_v2 `/api/v1/internal/llm-usage/*`) instead of the usage tables. Its admin dashboard (LLM Usage tab) and monthly budget alert then replace this dashboard and the email settings above |

## Running locally

```sh
# API (from code_/, with the venv active, AWN_USAGE_DB_* set, and Postgres running for saved chats)
python -m scripts.migrate_conversations
AWN_ADMIN_TOKEN=change-me uvicorn backend.api:app --reload --port 8000

# chatbot (from code_/frontend/)
npm ci
VITE_API_TARGET=http://127.0.0.1:8000 npm run dev   # http://localhost:5173/

# dashboard (from code_/dashboard/)
npm ci
VITE_API_TARGET=http://127.0.0.1:8000 npm run dev   # http://localhost:5174/admin/
npm test   # runs testing/dashboard/*.test.ts
```

To preview with synthetic data (signed-in users with 2 day sessions, all labelled
"Includes demo data" and never counted toward the budget):

```sh
# from the repository root
PYTHONPATH=code_ python testing/seed_dashboard_demo.py          # ~120 days of demo traffic
PYTHONPATH=code_ python testing/seed_dashboard_demo.py --clear  # remove it again
```

## Deployment and open items

The dashboard is deployed with the rest of the app on an **AWS EC2 instance** (see `deployment/README.md`).

| Topic | Status |
| --- | --- |
| Mail server for the budget alert | **Later**, once there is access to the AWS EC2 repo: set the `AWN_SMTP_*` settings there. Until then the dashboard warns that alerts are not set up. On EC2, Amazon SES's SMTP interface works with these settings |
| Admin sign-in | **Later**, once there is access to the AWS EC2 repo. A shared token (`AWN_ADMIN_TOKEN`) until then |
| Usage database account | **Needed from AgWeatherNet**: an account for `AWN_USAGE_DB_*` with `SELECT, INSERT, UPDATE` on the `awn.table_llm_usage_*` tables (the chatbot's account is read only) |
| Users who have not used the chatbot | Needs the total number of signed-in website users (e.g. from the site's login system or GA4) |
| User satisfaction (thumbs up / down) | Not built; needs a feedback button in the chat app |
