import type { Metrics, RangeKey, UsersPage } from "./types.ts";

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

/** Fetch one page of per user costs, most expensive first. */
export async function fetchUsers(
  range: RangeKey,
  token: string,
  offset: number,
  limit: number,
  signal?: AbortSignal,
): Promise<UsersPage> {
  const query = new URLSearchParams({ range, offset: String(offset), limit: String(limit) });
  const response = await adminGet(`/api/admin/users?${query}`, token, signal);
  return (await response.json()) as UsersPage;
}

/** Download every user's costs as CSV (the header carries the token, so a plain link cannot be used). */
export async function downloadUsersCsv(range: RangeKey, token: string): Promise<void> {
  const response = await adminGet(`/api/admin/users.csv?range=${encodeURIComponent(range)}`, token);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `awn-llm-cost-by-user-${range}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
