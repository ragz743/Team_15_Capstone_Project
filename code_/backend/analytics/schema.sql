-- Usage analytics tables for the admin dashboard, in AgWeatherNet's MariaDB (`awn` database).
-- AgWeatherNet created these tables; this is a copy for reference and for the tests. The API never creates
-- or alters them, so its database account only needs SELECT, INSERT and UPDATE on them.
--
-- Notes on how the chatbot fills them:
--   kind is always 'chat' (the chatbot makes no embedding requests).
--   priced and cost_reported are both 1 when OpenRouter reported the call's cost, otherwise both 0 and
--   cost_usd is 0. Every cost is the one OpenRouter billed; there is no price list.
--   table_llm_usage_quality_runs has no cost column, so the daily quality check's model cost is not
--   counted toward the monthly budget.

-- 1. One row per call (one question answered end to end)
CREATE TABLE IF NOT EXISTS awn.table_llm_usage_requests (
  request_id  VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id     VARCHAR(64)  DEFAULT NULL,  -- AWN username; NULL when the chatbot could not tell
  session_id  VARCHAR(64)  DEFAULT NULL,  -- login session id
  started_at  DATETIME(3)  NOT NULL,      -- UTC
  latency_ms  INT          NOT NULL,      -- end to end time to answer
  status      VARCHAR(16)  NOT NULL,      -- ok | empty | error | rate_limited | unavailable
  error_type  VARCHAR(100) DEFAULT NULL,  -- exception class for failed calls, never the message
  is_demo     TINYINT(1)   NOT NULL DEFAULT 0,
  received_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_started_at (started_at),
  INDEX idx_user_started (user_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. One row per model request (chat or embedding) made during a call
CREATE TABLE IF NOT EXISTS awn.table_llm_usage_model_calls (
  id               BIGINT         AUTO_INCREMENT PRIMARY KEY,
  request_id       VARCHAR(64)    NOT NULL,
  called_at        DATETIME(3)    NOT NULL,           -- UTC
  kind             VARCHAR(16)    NOT NULL,           -- chat | embedding
  model            VARCHAR(128)   NOT NULL,
  input_tokens     INT            NOT NULL DEFAULT 0,
  output_tokens    INT            NOT NULL DEFAULT 0,
  tokens_estimated TINYINT(1)     NOT NULL DEFAULT 0, -- provider did not report token usage
  cost_usd         DECIMAL(16,10) NOT NULL DEFAULT 0,
  priced           TINYINT(1)     NOT NULL DEFAULT 0, -- 0 when no price was known (counted as $0)
  cost_reported    TINYINT(1)     NOT NULL DEFAULT 0, -- 1 when cost_usd is what the provider billed
  latency_ms       INT            DEFAULT NULL,
  succeeded        TINYINT(1)     NOT NULL DEFAULT 1,
  INDEX idx_request (request_id),
  CONSTRAINT fk_llm_usage_model_calls_request FOREIGN KEY (request_id)
    REFERENCES awn.table_llm_usage_requests (request_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. One row per daily retrieval quality check
CREATE TABLE IF NOT EXISTS awn.table_llm_usage_quality_runs (
  id       INT         AUTO_INCREMENT PRIMARY KEY,
  run_at   DATETIME(3) NOT NULL,  -- UTC
  samples  INT         NOT NULL,  -- sample questions evaluated
  passed   INT         NOT NULL,  -- questions whose expected weather data was retrieved
  details  MEDIUMTEXT  NOT NULL,  -- JSON array, per question results
  is_demo  TINYINT(1)  NOT NULL DEFAULT 0,
  INDEX idx_run_at (run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. One row per monthly budget alert (sent once per month across both servers)
CREATE TABLE IF NOT EXISTS awn.table_llm_usage_budget_alerts (
  month         DATE           NOT NULL,  -- first day of the month, TZ_DISPLAY
  threshold_usd DECIMAL(12,2)  NOT NULL,
  spent_usd     DECIMAL(16,10) NOT NULL,
  recipients    VARCHAR(512)   NOT NULL,
  attempted_at  DATETIME       NOT NULL,  -- UTC
  delivered     TINYINT(1)     NOT NULL DEFAULT 0,
  error         TEXT           DEFAULT NULL,
  PRIMARY KEY (month, threshold_usd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
