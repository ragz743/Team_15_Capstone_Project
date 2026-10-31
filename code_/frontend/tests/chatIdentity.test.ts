import assert from "node:assert/strict";
import { test } from "node:test";
import { createConversation, sendChat, sendSavedChat } from "../src/lib/api.ts";

const conversationId = "11111111-1111-4111-8111-111111111111";
const requestId = "22222222-2222-4222-8222-222222222222";
const reply = {
  reply: "72 F", model: "weather", outcome: "success", conversation_id: conversationId,
  request_id: requestId, context: { station_ids: [], county: null, start: null, end: null, subject: null },
};

test("both chat paths send the current AWN login identity and stop after logout", async (t) => {
  const host = { AWN_CHAT_IDENTITY: { userId: "sai@wsu.edu", sessionId: "login-1" } as unknown };
  Object.defineProperty(globalThis, "window", { configurable: true, value: host });
  t.after(() => Reflect.deleteProperty(globalThis, "window"));
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(reply));
  await sendChat([{ role: "user", content: "Weather?" }]);
  await sendSavedChat(conversationId, requestId, "Weather?");
  for (const call of fetch.mock.calls) {
    const headers = new Headers(call.arguments[1]?.headers);
    assert.equal(headers.get("X-AWN-User-Id"), "sai@wsu.edu");
    assert.equal(headers.get("X-AWN-Session-Id"), "login-1");
  }
  host.AWN_CHAT_IDENTITY = { userId: "other.user", sessionId: "login-2" };
  await sendSavedChat(conversationId, requestId, "Weather?");
  assert.equal(new Headers(fetch.mock.calls.at(-1)?.arguments[1]?.headers).get("X-AWN-Session-Id"), "login-2");
  for (const identity of [
    null, {}, { userId: "x".repeat(65), sessionId: "s" }, { userId: "user", sessionId: "bad id" },
    { userId: "user\n", sessionId: "s" }, { userId: "user", sessionId: "s\r\n" },
  ]) {
    host.AWN_CHAT_IDENTITY = identity;
    await sendSavedChat(conversationId, requestId, "Weather?");
    const headers = new Headers(fetch.mock.calls.at(-1)?.arguments[1]?.headers);
    assert.equal(headers.get("X-AWN-User-Id"), null);
    assert.equal(headers.get("X-AWN-Session-Id"), null);
  }
});

test("identity headers are limited to chat calls", async (t) => {
  Object.defineProperty(globalThis, "window", { configurable: true,
    value: { AWN_CHAT_IDENTITY: { userId: "sai", sessionId: "login-1" } } });
  t.after(() => Reflect.deleteProperty(globalThis, "window"));
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    id: conversationId, title: "New conversation", created_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z",
  }));
  await createConversation();
  assert.equal(new Headers(fetch.mock.calls[0].arguments[1]?.headers).get("X-AWN-User-Id"), null);
});
