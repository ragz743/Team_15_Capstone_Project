/** Non-secret analytics IDs supplied by the signed-in AWN host. */
export type ChatIdentity = { userId: string; sessionId: string };

declare global {
  interface Window {
    AWN_CHAT_IDENTITY?: ChatIdentity | null;
  }
}

function isClientId(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 64 && !/[^A-Za-z0-9._@-]/.test(value);
}

/** Read on every send so login, logout, and session changes take effect immediately. */
export function chatIdentityHeaders(): Record<string, string> {
  const identity = typeof window === "undefined" ? undefined : window.AWN_CHAT_IDENTITY;
  if (!identity || !isClientId(identity.userId) || !isClientId(identity.sessionId)) return {};

  return { "X-AWN-User-Id": identity.userId, "X-AWN-Session-Id": identity.sessionId };
}
