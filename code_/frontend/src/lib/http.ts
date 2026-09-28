export const API_BASE = import.meta.env?.VITE_API_BASE ?? "";

/** Error thrown by the API client so callers can surface a friendly message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function errorDetail(status: number, body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) return undefined;
  if (typeof body.detail === "string") return body.detail.trim() || undefined;
  if (status === 422 && Array.isArray(body.detail)) {
    return (
      body.detail
        .filter(
          (error): error is { msg: string } =>
            typeof error === "object" && error !== null && "msg" in error && typeof error.msg === "string",
        )
        .map((error) => error.msg.trim())
        .filter(Boolean)
        .join("; ") || undefined
    );
  }
  return undefined;
}

/**
 * Build a user-friendly message for a failed HTTP response.
 */
function friendlyErrorMessage(status: number, detail: string | undefined): string {
  if (detail) {
    return detail;
  }
  if (status === 422) {
    return "The chat request is invalid. Please check your message and try again.";
  }
  if (status === 502 || status === 504) {
    return "The weather service could not complete your request. Please try again.";
  }
  if (status === 503) {
    return "The weather service is temporarily unavailable. Please try again later.";
  }
  return `Backend returned ${status}`;
}

function invalidResponse(status: number): ApiError {
  return new ApiError(status, "The weather service returned an invalid response. Please try again.");
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (response.ok) throw invalidResponse(response.status);
    return undefined;
  }
}

export async function requestJson<T>(
  path: string,
  options: RequestInit,
  validate: (value: unknown) => value is T,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: "include", ...options });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Network error. Could not reach the AWN backend.");
  }
  const body = await readJson(response);
  if (!response.ok) {
    const detail = errorDetail(response.status, body);
    throw new ApiError(response.status, friendlyErrorMessage(response.status, detail), detail);
  }
  if (!validate(body)) throw invalidResponse(response.status);
  return body;
}

export function jsonPost(body: unknown, signal?: AbortSignal): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal };
}
