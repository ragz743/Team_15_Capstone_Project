-- Preserve accepted inputs and resolved constraints independently of query attempts.
ALTER TABLE conversation_turns
    ADD COLUMN IF NOT EXISTS request_input JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS prepared_turn JSONB,
    ADD COLUMN IF NOT EXISTS result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
