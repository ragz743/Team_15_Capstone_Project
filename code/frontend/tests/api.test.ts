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

test("displays FastAPI validation messages for a rejected chat request", async (t) => {
  const detail = [
    {
      type: "string_too_long",
      loc: ["body", "messages", 0, "content"],
      msg: "String should have at most 4000 characters",
      input: "a".repeat(4001),
      ctx: { max_length: 4000 },
    },
    {
      type: "extra_forbidden",
      loc: ["body", "extra"],
      msg: "Extra inputs are not permitted",
      input: "unexpected field",
    },
  ];
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail }, { status: 422 }));

  await assert.rejects(sendChat(messages), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 422);
    assert.equal(error.detail, "String should have at most 4000 characters; Extra inputs are not permitted");
    assert.equal(error.message, error.detail);
    return true;
  });
});

test("ignores invalid entries alongside a readable validation message", async (t) => {
  const detail = [null, {}, { msg: 12 }, { msg: " " }, { msg: "Conversation exceeds 32000 characters" }];
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail }, { status: 422 }));

  await assert.rejects(sendChat(messages), {
    name: "ApiError",
    message: "Conversation exceeds 32000 characters",
  });
});

for (const body of [{ detail: [] }, { detail: [{ msg: null }] }, { detail: " " }, {}]) {
  test(`explains a 422 response without readable details: ${JSON.stringify(body)}`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json(body, { status: 422 }));
    await assert.rejects(sendChat(messages), {
      name: "ApiError",
      message: "The chat request is invalid. Please check your message and try again.",
    });
  });
}

test("explains a non-JSON 422 response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("Invalid request", { status: 422 }));
  await assert.rejects(sendChat(messages), {
    name: "ApiError",
    message: "The chat request is invalid. Please check your message and try again.",
  });
});

test("preserves a string validation detail", async (t) => {
  const detail = "Please enter a weather related question.";
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail }, { status: 422 }));
  await assert.rejects(sendChat(messages), { name: "ApiError", message: detail, detail });
});

for (const status of [502, 503, 504]) {
  test(`handles a non-JSON ${status} response`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => new Response("proxy error", { status }));
    await assert.rejects(sendChat(messages), { name: "ApiError", message: /weather service/ });
  });
}

test("reports a network failure", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(sendChat(messages), { name: "ApiError", message: /Network error/ });
});

for (const phase of ["connecting", "reading a reply", "reading an error"]) {
  test(`preserves cancellation while ${phase}`, async (t) => {
    const aborted = new DOMException("Cancelled", "AbortError");
    t.mock.method(globalThis, "fetch", async () => {
      if (phase === "connecting") throw aborted;
      const response = Response.json({}, { status: phase === "reading an error" ? 502 : 200 });
      t.mock.method(response, "json", async () => { throw aborted; });
      return response;
    });
    await assert.rejects(sendChat(messages), (error) => error === aborted);
  });
}
