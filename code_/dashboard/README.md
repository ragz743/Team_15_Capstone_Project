# AWN admin dashboard

An admin-only page for tracking the AgWeatherNet weather assistant's users, retrieval quality, LLM spending,
and performance. It is served at `/admin/` alongside the chat app, which will run on an AWS EC2 instance, and
reads from the `/api/admin/*` endpoints.

| Section | What it shows |
| --- | --- |
| Overview | Active users, successful sessions, retrieval quality, calls, share answered within 5 s, LLM spending, cost per 1,000 calls, failed calls; each compared with the previous period |
| Users and sessions | Active users and successful sessions per day, week, or month |
| Cost per user | Every logged-in user's calls, sessions, tokens, and spending: searchable, sortable, CSV export |
| Retrieval quality | Score of each daily sample check, and the latest check question by question |
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
| Call | One question answered end to end. Each call makes several model requests (chat and embedding) |
| LLM spending | Real spending on model requests only (no hosting, no projections). OpenRouter's free models cost $0 |
| Retrieval quality | Share of a fixed sample of questions for which the right weather data was found, checked daily rather than on every call |
| Response time target | Under 5 seconds, end to end |
| Budget | Email weather@wsu.edu once a month's real spending passes $50 |

## How the data is collected

The API records every `/api/chat` call in Postgres (tables are created automatically at startup, see
`backend/analytics/schema.sql`):

- `usage_requests`: one row per call with its user ID, login session ID, response time, and outcome
- `usage_llm_calls`: one row per model request with its model, tokens, and cost
- `usage_quality_runs`: one row per retrieval quality check
- `usage_budget_alerts`: one row per month once spending passes the budget, so the email goes out once

Chat model requests are captured with a LangChain callback, so any `_BaseChatbot` and every LangGraph workflow
step is measured without changes. No question or answer text is stored. Recording never fails a chat request.

### Users and sessions

The chat app identifies the signed-in user by sending two headers with each `/api/chat` request:

| Header | Meaning |
| --- | --- |
| `X-AWN-User-Id` | the signed-in user's ID (always present, since signing in is required) |
| `X-AWN-Session-Id` | the login session ID |

Both accept 1-64 characters of `A-Z a-z 0-9 _ -`.

### Spending

Spending = tokens × the price per token in [`backend/analytics/pricing.yaml`](../backend/analytics/pricing.yaml),
or the exact amount when the provider reports one. Models ending in `:free` cost $0; a model missing from the file
is counted as $0 and the dashboard warns that spending is understated.

### Retrieval quality

The API runs the check once a day (whenever the last run is over 24 hours old). It asks each question in
[`backend/analytics/retrieval_samples.yaml`](../backend/analytics/retrieval_samples.yaml) and passes it when the
retriever returns records for the expected station or county from the expected data (current, past 7 days, or
forecast). Keep the sample in step with the stations in the index. To run it now:

```sh
python -m scripts.evaluate_retrieval            # evaluate and save
python -m scripts.evaluate_retrieval --dry-run  # print results only
```

### Budget alert

Every hour the API compares this month's real spending (demo data excluded) with the budget. Once it passes,
one email goes to the alert address; a failed send is retried hourly and shown on the dashboard. **The email is
only sent once SMTP is configured** (see below).

## Configuration (API environment)

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWN_ADMIN_TOKEN` | unset | Token admins enter to sign in. The dashboard is disabled until this is set |
| `AWN_DASHBOARD_TIMEZONE` | `America/Los_Angeles` | Timezone for days, months, and the monthly budget |
| `AWN_RESPONSE_TARGET_MS` | `5000` | Response time target |
| `AWN_QUALITY_CHECK_HOURS` | `24` | How often the retrieval quality check runs |
| `AWN_MONTHLY_BUDGET_USD` | `50` | Monthly spending that triggers the alert |
| `AWN_BUDGET_ALERT_EMAIL` | `weather@wsu.edu` | Alert recipients (comma separated) |
| `AWN_SMTP_HOST`, `AWN_SMTP_PORT`, `AWN_SMTP_USERNAME`, `AWN_SMTP_PASSWORD`, `AWN_SMTP_FROM`, `AWN_SMTP_STARTTLS` | unset, `587`, unset, unset, unset, `true` | Mail server for the budget alert |
| `AWN_DASHBOARD_URL` | unset | Link included in the alert email |
| `AWN_USAGE_TRACKING` | `true` | Set to `false` to stop recording usage |
| `AWN_BACKEND_URL`, `AWN_INTERNAL_KEY` | unset | When both are set, usage and quality checks are sent to the AgWeatherNet backend (awn_be_v2 `/api/v1/internal/llm-usage/*`) instead of Postgres. Its admin dashboard (LLM Usage tab) and monthly budget alert then replace this dashboard and the email settings above |
| `AWN_PRICING_FILE` | bundled `pricing.yaml` | Alternative price table |

## Running locally

```sh
# API (from code_/, with the venv active and Postgres running)
AWN_ADMIN_TOKEN=change-me uvicorn backend.api:app --reload --port 8000

# dashboard (from code_/dashboard/)
npm install
VITE_API_TARGET=http://127.0.0.1:8000 npm run dev   # http://localhost:5174/admin/
npm test
```

To preview with synthetic data (signed-in users with 2 day sessions and daily quality checks, all labelled
"Includes demo data" and never counted toward the budget):

```sh
python -m scripts.seed_dashboard_demo          # ~120 days of demo traffic
python -m scripts.seed_dashboard_demo --clear  # remove it again
```

## Deployment and open items

The dashboard is deployed with the rest of the app on an **AWS EC2 instance** (see `deployment/README.md`).

| Topic | Status |
| --- | --- |
| Mail server for the budget alert | **Later**, once there is access to the AWS EC2 repo: set the `AWN_SMTP_*` settings there. Until then the dashboard warns that alerts are not set up. On EC2, Amazon SES's SMTP interface works with these settings |
| Admin sign-in | **Later**, once there is access to the AWS EC2 repo. A shared token (`AWN_ADMIN_TOKEN`) until then |
| Users who have not used the chatbot | Needs the total number of signed-in website users (e.g. from the site's login system or GA4) |
| User satisfaction (thumbs up / down) | Not built; needs a feedback button in the chat app |
