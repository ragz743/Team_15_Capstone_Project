/** Shapes returned by GET /api/admin/metrics (see backend/analytics/usage_store.py). */

export type RangeKey = "7d" | "30d" | "90d" | "12m";
export type Bucket = "day" | "week" | "month";

/**
 * A "call" is one attempt to answer a question. "Model requests" are requests made inside a call.
 * "Users" are logged-in users identified by the host website. Calls without a host user ID remain
 * unidentified and count toward model usage and spending, but not users or login sessions.
 * A session is one login session; it is successful when every call in it was answered.
 */
export type Summary = {
  calls: number;
  unidentified_calls: number;
  failed_calls: number;
  error_rate: number | null;
  users: number;
  sessions: number;
  successful_sessions: number;
  successful_session_rate: number | null;
  avg_sessions_per_user: number | null;
  avg_calls_per_session: number | null;
  model_requests: number;
  cost_usd: number;
  avg_cost_per_user: number | null;
  avg_cost_per_call: number | null;
  cost_per_1000_calls: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  within_target_rate: number | null;
};

export type SeriesPoint = {
  bucket: string; // YYYY-MM-DD, start of the day / week / month in the dashboard timezone
  calls: number;
  unidentified_calls: number;
  failed_calls: number;
  error_rate: number | null;
  users: number;
  sessions: number;
  successful_sessions: number;
  successful_session_rate: number | null;
  avg_sessions_per_user: number | null;
  model_requests: number;
  cost_usd: number;
  avg_cost_per_user: number | null;
  cost_per_1000_calls: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  within_target_rate: number | null;
};

export type QualityRun = {
  run_at: string;
  samples: number;
  passed: number;
  score: number | null;
  is_demo: boolean;
};

export type QualityDetail = {
  question: string;
  source: "current" | "historical" | "forecast";
  expected: string;
  passed: boolean;
  found: string[];
  error: string | null;
};

export type Budget = {
  month: string;
  threshold_usd: number;
  spent_usd: number;
  used: number | null;
  email_configured: boolean;
  recipients: string;
  alert: { attempted_at: string | null; delivered: boolean; error: string | null; recipients: string } | null;
};

export type ModelRow = {
  kind: "chat" | "embedding";
  model: string;
  calls: number;
  failed_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_cost_per_call: number | null;
  priced: boolean;
  /** billed: the provider reported the cost; estimated: tokens × pricing.yaml; unpriced: no price known. */
  cost_source: "billed" | "estimated" | "mixed" | "unpriced";
  tokens_estimated: boolean;
  latency_p50_ms: number | null;
};

export type Metrics = {
  range: { start: string; end: string; days: number; bucket: Bucket; timezone: string };
  includes_demo_data: boolean;
  target_ms: number;
  summary: Summary;
  previous: Summary;
  series: SeriesPoint[];
  by_model: ModelRow[];
  by_status: { status: string; requests: number }[];
  quality: { runs: QualityRun[]; latest: (QualityRun & { details: QualityDetail[] }) | null };
  budget: Budget;
};

export type UserRow = {
  user_id: string | null; // null for the unidentified group
  requests: number;
  sessions: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cost_share: number | null;
  avg_cost_per_request: number | null;
  first_seen: string | null;
  last_seen: string | null;
};

/** Columns /api/admin/users can sort by (backend/analytics/usage_store.py UserSort). */
export type UserSortField =
  | "user_id"
  | "requests"
  | "sessions"
  | "llm_calls"
  | "total_tokens"
  | "cost_usd"
  | "avg_cost_per_request"
  | "last_seen";

export type UserQuery = { search: string; sort: UserSortField; order: "asc" | "desc" };

/** GET /api/admin/users: one page of users matching the search, in the requested order. */
export type UsersPage = {
  total_users: number;
  /** Users matching the search (equals total_users without a search). */
  matched_users: number;
  search: string | null;
  total_cost_usd: number;
  top_decile_cost_share: number | null;
  limit: number;
  offset: number;
  users: UserRow[];
  unidentified: UserRow | null;
};
