import assert from "node:assert/strict";
import { test } from "node:test";
import { sendChat } from "../src/lib/api.ts";

const messages = [{ role: "user" as const, content: "Weather in Pullman?" }];

test("sends the conversation and cancellation signal, and returns the answer", async (t) => {
  const controller = new AbortController();
  const reply = { reply: "Pullman: 72°F.", model: "test-model" };
  const fetchMock = t.mock.method(globalThis, "fetch", async () => Response.json(reply));

  assert.deepEqual(await sendChat(messages, controller.signal), reply);
  assert.equal(fetchMock.mock.callCount(), 1);
  const [url, options] = fetchMock.mock.calls[0].arguments;
  assert.equal(url, "/api/chat");
  assert.ok(options);
  assert.equal(options.method, "POST");
  assert.ok(typeof options.body === "string");
  assert.deepEqual(JSON.parse(options.body), { messages });
  assert.equal(new Headers(options.headers).get("Content-Type"), "application/json");
  assert.equal(options.signal, controller.signal);
});
