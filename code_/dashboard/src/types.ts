/** Shapes returned by GET /api/admin/metrics (see backend/analytics/usage_store.py). */

export type RangeKey = "7d" | "30d" | "90d" | "12m";

export type Summary = {
  requests: number;
  unidentified_requests: number;
  failed_requests: number;
  error_rate: number | null;
  users: number;
  sessions: number;
  avg_sessions_per_user: number | null;
  avg_requests_per_session: number | null;
  chat_calls: number;
  embedding_calls: number;
  llm_calls: number;
  cost_usd: number;
  avg_cost_per_user: number | null;
  avg_cost_per_call: number | null;
  avg_cost_per_request: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
};

export type SeriesPoint = {
  bucket: string; // YYYY-MM-DD, start of the day / week / month in the dashboard timezone
  requests: number;
  failed_requests: number;
  error_rate: number | null;
  users: number;
  avg_sessions_per_user: number | null;
  chat_calls: number;
  embedding_calls: number;
  llm_calls: number;
  cost_usd: number;
  avg_cost_per_user: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
};

export type MonthPoint = SeriesPoint & { partial: boolean };

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
  tokens_estimated: boolean;
  latency_p50_ms: number | null;
};

export type Metrics = {
  range: { start: string; end: string; days: number; bucket: "day" | "week"; timezone: string };
  includes_demo_data: boolean;
  summary: Summary;
  previous: Summary;
  series: SeriesPoint[];
  months: MonthPoint[];
  by_model: ModelRow[];
  by_status: { status: string; requests: number }[];
};
