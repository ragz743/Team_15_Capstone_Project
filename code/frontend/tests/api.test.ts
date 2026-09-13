import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, sendChat } from "../src/lib/api.ts";

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

for (const body of [null, {}, { reply: 72, model: "test" }, { reply: " \n", model: "test" }, { reply: "72°F" }]) {
  test(`rejects malformed successful response: ${JSON.stringify(body)}`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json(body));
    await assert.rejects(sendChat(messages), { name: "ApiError", message: /invalid response/ });
  });
}

test("rejects a non-JSON successful response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("<html>proxy page</html>"));
  await assert.rejects(sendChat(messages), { name: "ApiError", message: /invalid response/ });
});

test("preserves a useful backend error", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Please enter a weather related question." }, { status: 400 }));
  await assert.rejects(sendChat(messages), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 400);
    assert.equal(error.detail, "Please enter a weather related question.");
    return true;
  });
});

for (const status of [502, 503, 504]) {
  test(`handles a non-JSON ${status} response`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => new Response("proxy error", { status }));
    await assert.rejects(sendChat(messages), { name: "ApiError", message: /weather service/ });
  });
}
