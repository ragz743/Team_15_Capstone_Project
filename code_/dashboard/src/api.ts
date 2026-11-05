import type { Bucket, Metrics, RangeKey, UserQuery, UsersPage } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function adminGet(path: string, token: string, signal?: AbortSignal): Promise<Response> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, signal });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non JSON error body, keep the generic message
    }
    throw new ApiError(response.status, detail);
  }
  return response;
}

/** Fetch dashboard metrics for a range at a daily, weekly, or monthly granularity. */
export async function fetchMetrics(range: RangeKey, bucket: Bucket, token: string, signal?: AbortSignal): Promise<Metrics> {
  const response = await adminGet(`/api/admin/metrics?${new URLSearchParams({ range, bucket })}`, token, signal);
  return (await response.json()) as Metrics;
}

/** Save a browser download of a response body (the token travels in a header, so a plain link cannot be used). */
async function saveDownload(response: Response, filename: string): Promise<void> {
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Download the time series behind the charts as CSV. */
export async function downloadMetricsCsv(range: RangeKey, bucket: Bucket, token: string): Promise<void> {
  const response = await adminGet(`/api/admin/metrics.csv?${new URLSearchParams({ range, bucket })}`, token);
  await saveDownload(response, `awn-llm-usage-${range}-by-${bucket}.csv`);
}

function userParams(range: RangeKey, query: UserQuery): URLSearchParams {
  const params = new URLSearchParams({ range, sort: query.sort, order: query.order });
  if (query.search.trim()) params.set("search", query.search.trim());
  return params;
}

/** Fetch one page of per user costs, filtered and sorted on the server. */
export async function fetchUsers(
  range: RangeKey,
  token: string,
  query: UserQuery,
  offset: number,
  limit: number,
  signal?: AbortSignal,
): Promise<UsersPage> {
  const params = userParams(range, query);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  const response = await adminGet(`/api/admin/users?${params}`, token, signal);
  return (await response.json()) as UsersPage;
}

/** Download the users in the table, every page, as CSV (the header carries the token, so a plain link cannot be used). */
export async function downloadUsersCsv(range: RangeKey, token: string, query: UserQuery): Promise<void> {
  const response = await adminGet(`/api/admin/users.csv?${userParams(range, query)}`, token);
  await saveDownload(response, `awn-llm-cost-by-user-${range}.csv`);
}
