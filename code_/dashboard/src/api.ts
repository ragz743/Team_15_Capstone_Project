import type { Metrics, RangeKey } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Fetch dashboard metrics for a range, authenticating with the admin token. */
export async function fetchMetrics(range: RangeKey, token: string, signal?: AbortSignal): Promise<Metrics> {
  const response = await fetch(`/api/admin/metrics?range=${encodeURIComponent(range)}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });

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

  return (await response.json()) as Metrics;
}
