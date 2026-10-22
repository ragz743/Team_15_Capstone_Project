import type { Metrics, RangeKey, UserQuery, UsersPage } from "./types.ts";

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

/** Fetch dashboard metrics for a range, authenticating with the admin token. */
export async function fetchMetrics(range: RangeKey, token: string, signal?: AbortSignal): Promise<Metrics> {
  const response = await adminGet(`/api/admin/metrics?range=${encodeURIComponent(range)}`, token, signal);
  return (await response.json()) as Metrics;
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
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `awn-llm-cost-by-user-${range}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
