# Usage analytics (admin dashboard backend)

This package records what the chatbot costs and how well it works, and serves that to the admin dashboard
(`code_/dashboard`, at `/admin/`). It does not change how questions are answered. For what the dashboard
shows and how to run it, see [`code_/dashboard/README.md`](../../dashboard/README.md).

## Where the data comes from

```text
POST /api/chat (api.py)
  └─ UsageTracker.track()                    one row per question: user, session, latency, outcome
       └─ metered()                          LangChain callback attached to every model call inside
            └─ LangGraph workflow            classifier, SQL generation, summary: each call's model,
                                             tokens, and the cost OpenRouter reports
  └─ UsageStore.record()  ──> Postgres       usage_requests + usage_llm_calls
       or AwnUsageReporter ──> AgWeatherNet backend (when AWN_BACKEND_URL is set)

GET /api/admin/* (admin_api.py)  ──> UsageStore SQL queries ──> dashboard
```

- **Per question:** `api.py` wraps each `/api/chat` request in `UsageTracker.track()`, which times it and
  stores its outcome (answered, empty, error, rate limited, unavailable).
- **Per model call:** `metering.py` registers a LangChain callback for the duration of the request. LangChain
  calls it for every chat model request, so the workflow needs no analytics code: the classifier, SQL
  generation and summary nodes are all captured because they use LangChain models. This is why there are
  only small changes in `backend/workflow/`.
- **Cost:** OpenRouter returns the billed cost of every request in its response
  ([usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)), and that is the
  cost recorded. Nothing is estimated and there is no price list to maintain. A provider that does not report
  a cost (for example a local llama.cpp model) is recorded at $0 and the dashboard flags it.
- **Retrieval quality:** `retrieval_quality.py` is production monitoring, not a test. Once a day the API
  asks the questions in `retrieval_samples.yaml` through the same workflow and records whether it read
  the right kind of weather data at the right station. Its model cost counts toward the monthly budget.
- **Budget alert:** `budget.py` checks month-to-date spending every hour and emails the team once per month
  when it passes the budget.

No question or answer text is stored, only counts, tokens, costs, timings and outcomes.

### How we know it is accurate

- Token counts and cost come from the provider's own response, not from estimates. When a provider omits
  token counts they are estimated from the text length and shown with `~` on the dashboard.
- `testing/backend/workflow/test_workflow_metering.py` runs the real workflow and checks that every model
  call (classifier, each query node, summary) is recorded exactly once with its tokens and cost.
- `testing/backend/test_usage_store.py` runs the dashboard's SQL against a real Postgres schema and checks
  the totals add up.
- The numbers can be compared with the OpenRouter activity page for the same API key.

## Where Postgres is used

The project's Postgres (the `pgvector` service in Docker, configured with `PG_USER`, `PG_PASSWORD`,
`PG_HOST`, `PG_PORT`) holds:

| Tables | Used for | Created by |
| --- | --- | --- |
| `conversations`, `conversation_turns`, station directory tables | Saved chat history and station lookup | `deployment/migrations/*.sql` |
| `usage_requests`, `usage_llm_calls`, `usage_quality_runs`, `usage_budget_alerts` | This dashboard | `schema.sql`, applied automatically at API startup |

The weather data itself is read from AgWeatherNet's MySQL databases, not Postgres.

If the client would rather not run Postgres for analytics, set `AWN_BACKEND_URL` and `AWN_INTERNAL_KEY`:
usage is then sent to the AgWeatherNet backend (`awn_reporter.py`) and shown in its own admin dashboard,
and none of the `usage_*` tables are used.

## Settings

All settings are environment variables in the repository's `.env` file (loaded by `api.py`). None are
required for the chatbot itself to run.

| Variable | Needed for | How to set it |
| --- | --- | --- |
| `AWN_ADMIN_TOKEN` | Signing in to the dashboard | A placeholder login until the dashboard uses the AWN website's admin sign-in: any value works (the project `.env` uses a dummy one), and admins type the same value to sign in. The dashboard is disabled while it is unset |
| `AWN_MONTHLY_BUDGET_USD`, `AWN_BUDGET_ALERT_EMAIL` | Budget alert | Optional; default $50 and `weather@wsu.edu` |
| `AWN_SMTP_HOST`, `AWN_SMTP_FROM` | Emailing the alert | Optional, but set both or neither |
| `AWN_SMTP_USERNAME`, `AWN_SMTP_PASSWORD` | Mail servers that need a login | Optional, but set both or neither |
| `AWN_BACKEND_URL`, `AWN_INTERNAL_KEY` | Sending usage to the AgWeatherNet backend instead of Postgres | From the AgWeatherNet backend team |

The full list, with defaults, is in the dashboard README's
[configuration table](../../dashboard/README.md#configuration-api-environment). The budget and email
settings are checked when the API starts, so a partial setup fails immediately with a message naming the
missing variable instead of failing when the first alert is due.

## Files

| File | Purpose |
| --- | --- |
| `metering.py` | Captures each model call's tokens and reported cost during a request |
| `usage_store.py` | Writes usage to Postgres and runs the dashboard's metric queries |
| `schema.sql` | The `usage_*` tables |
| `admin_api.py` | The `/api/admin/*` endpoints the dashboard reads |
| `awn_reporter.py` | Alternative to `usage_store.py`: sends usage to the AgWeatherNet backend |
| `budget.py` | Monthly budget check and alert email |
| `retrieval_quality.py`, `retrieval_samples.yaml` | Daily retrieval quality check and its questions |

`testing/seed_dashboard_demo.py` fills the tables with labelled demo data for previewing the dashboard.
