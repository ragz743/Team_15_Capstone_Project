CREATE INDEX IF NOT EXISTS conversation_turns_conversation_requested_idx
    ON conversation_turns (conversation_id, requested_at DESC, ordinal DESC);
