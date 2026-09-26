CREATE TABLE IF NOT EXISTS browser_owners (
    id UUID PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '365 days'
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES browser_owners(id),
    title TEXT NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    context JSONB NOT NULL DEFAULT '{}',
    next_ordinal INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS conversations_owner_updated_idx ON conversations (owner_id, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS conversation_turns (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    user_content TEXT NOT NULL CHECK (length(user_content) BETWEEN 1 AND 4000),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    attempt_id UUID NOT NULL,
    lease_until TIMESTAMPTZ NOT NULL,
    assistant_content TEXT,
    completed_at TIMESTAMPTZ,
    model TEXT,
    context JSONB,
    PRIMARY KEY (conversation_id, request_id),
    UNIQUE (conversation_id, ordinal),
    CHECK ((status = 'completed') = (assistant_content IS NOT NULL AND completed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS conversation_turns_requested_idx ON conversation_turns (requested_at DESC);
