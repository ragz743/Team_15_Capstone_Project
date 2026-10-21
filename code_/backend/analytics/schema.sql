-- Usage analytics tables for the admin dashboard.
-- Applied idempotently by UsageStore.ensure_schema() when the API starts.

-- one row per /api/chat request
CREATE TABLE IF NOT EXISTS usage_requests (
    request_id UUID PRIMARY KEY,
    user_id TEXT,                   -- anonymous client id supplied by the chat frontend, NULL when unknown
    session_id TEXT,                -- conversation id supplied by the chat frontend, NULL when unknown
    started_at TIMESTAMPTZ NOT NULL,
    latency_ms INTEGER NOT NULL,    -- end to end time spent answering the request
    status TEXT NOT NULL CHECK (status IN ('ok', 'empty', 'error', 'rate_limited', 'unavailable')),
    error_type TEXT,                -- exception class name for failed requests, never the message
    is_demo BOOLEAN NOT NULL DEFAULT false  -- synthetic rows written by scripts/seed_dashboard_demo.py
);
CREATE INDEX IF NOT EXISTS usage_requests_started_idx ON usage_requests (started_at);

-- one row per model call (chat completion or embedding) made while answering a request
CREATE TABLE IF NOT EXISTS usage_llm_calls (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES usage_requests (request_id) ON DELETE CASCADE,
    called_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('chat', 'embedding')),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_estimated BOOLEAN NOT NULL DEFAULT false,  -- true when the provider did not report token usage
    cost_usd NUMERIC(16, 10) NOT NULL DEFAULT 0,      -- priced when recorded so later price changes keep history
    priced BOOLEAN NOT NULL DEFAULT false,            -- false when the model is missing from pricing.yaml
    latency_ms INTEGER,
    succeeded BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS usage_llm_calls_request_idx ON usage_llm_calls (request_id);
