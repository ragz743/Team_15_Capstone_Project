-- Usage analytics tables for the admin dashboard.
-- Applied idempotently by UsageStore.ensure_schema() when the API starts.

-- one row per /api/chat request
CREATE TABLE IF NOT EXISTS usage_requests (
    request_id UUID PRIMARY KEY,
    user_id TEXT,                   -- signed-in AWN user id, NULL when unknown
    session_id TEXT,                -- non-secret login session id, NULL when unknown
    started_at TIMESTAMPTZ NOT NULL,
    latency_ms INTEGER NOT NULL,    -- end to end time spent answering the request
    status TEXT NOT NULL CHECK (status IN ('ok', 'empty', 'error', 'rate_limited', 'unavailable')),
    error_type TEXT,                -- exception class name for failed requests, never the message
    is_demo BOOLEAN NOT NULL DEFAULT false  -- synthetic rows written by testing/seed_dashboard_demo.py
);
CREATE INDEX IF NOT EXISTS usage_requests_started_idx ON usage_requests (started_at);

-- one row per chat model call made while answering a request
CREATE TABLE IF NOT EXISTS usage_llm_calls (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES usage_requests (request_id) ON DELETE CASCADE,
    called_at TIMESTAMPTZ NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_estimated BOOLEAN NOT NULL DEFAULT false,  -- true when the provider did not report token usage
    cost_usd NUMERIC(16, 10) NOT NULL DEFAULT 0,      -- cost OpenRouter reported for the call, 0 when not reported
    latency_ms INTEGER,
    succeeded BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS usage_llm_calls_request_idx ON usage_llm_calls (request_id);

-- true when OpenRouter reported the call's cost; false means cost_usd is an unknown cost recorded as 0
-- (added after the first release, so existing databases get the column here)
ALTER TABLE usage_llm_calls ADD COLUMN IF NOT EXISTS cost_reported BOOLEAN NOT NULL DEFAULT false;
-- every call is a chat model call, and its cost is the one OpenRouter reports, so the old kind and
-- priced columns are dropped here so existing databases match
ALTER TABLE usage_llm_calls DROP COLUMN IF EXISTS kind;
ALTER TABLE usage_llm_calls DROP COLUMN IF EXISTS priced;

-- one row per run of the sampled retrieval quality check (scripts/evaluate_retrieval.py)
CREATE TABLE IF NOT EXISTS usage_quality_runs (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    samples INTEGER NOT NULL,         -- questions evaluated
    passed INTEGER NOT NULL,          -- questions whose expected weather data was retrieved
    details JSONB NOT NULL DEFAULT '[]',  -- per question results, for the latest run table
    is_demo BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS usage_quality_runs_run_at_idx ON usage_quality_runs (run_at);
-- model cost of the run's sample questions; not a user request, but it counts toward the monthly budget
ALTER TABLE usage_quality_runs ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(16, 10) NOT NULL DEFAULT 0;

-- monthly budget alerts; one row per month and threshold so an alert is emailed at most once
CREATE TABLE IF NOT EXISTS usage_budget_alerts (
    month DATE NOT NULL,              -- first day of the month, dashboard timezone
    threshold_usd NUMERIC(12, 2) NOT NULL,
    spent_usd NUMERIC(16, 10) NOT NULL,
    recipients TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered BOOLEAN NOT NULL DEFAULT false,
    error TEXT,
    PRIMARY KEY (month, threshold_usd)
);
