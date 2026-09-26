import assert from "node:assert/strict";
import { test } from "node:test";
import { createConversation, listConversations, loadConversation, sendSavedChat } from "../src/lib/api.ts";
import { RequestScope } from "../src/lib/requestScope.ts";

const conversation = "11111111-1111-4111-8111-111111111111";
const request = "22222222-2222-4222-8222-222222222222";
const context = {station_ids: ["1"], county: null, start: "2026-09-10", end: "2026-09-10", subject: "temperature"};
const reply = {reply: "72 F", model: "fixture", context, conversation_id: conversation, request_id: request};
const summary = {id: conversation, title: "Temperature?", created_at: "2026-09-10T18:00:00Z", updated_at: "2026-09-10T18:00:01Z"};

test("a saved turn sends one message, a stable retry ID and browser credentials", async (t) => {
  const controller = new AbortController();
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(reply));
  assert.deepEqual(await sendSavedChat(conversation, request, "Temperature?", controller.signal), reply);
  await sendSavedChat(conversation, request, "Temperature?", controller.signal);
  for (const { arguments: [, options] } of fetch.mock.calls) {
    assert.equal(options?.credentials, "include");
    assert.equal(options?.signal, controller.signal);
    assert.deepEqual(JSON.parse(String(options?.body)), {conversation_id: conversation, request_id: request, message: "Temperature?"});
  }
});

for (const invalid of [null, {...reply, conversation_id: request}, {...reply, request_id: conversation}, {...reply, reply: " "}, {...reply, context: {}}]) {
  test(`rejects a malformed or mismatched saved response: ${JSON.stringify(invalid)}`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json(invalid));
    await assert.rejects(sendSavedChat(conversation, request, "Temperature?"), /invalid response/);
  });
}

test("list, create and resume validate dated history and send credentials", async (t) => {
  const saved = {...summary, context, messages: [{id: `${request}:user`, request_id: request, role: "user", content: "Temperature?", created_at: summary.created_at, status: "completed"}], next_before: null};
  const fetch = t.mock.method(globalThis, "fetch", async (url: string | URL | Request, options?: RequestInit) => {
    if (options?.method === "POST") return Response.json(summary);
    if (String(url).endsWith(conversation)) return Response.json(saved);
    return Response.json({conversations: [summary]});
  });
  assert.deepEqual(await listConversations(), [summary]);
  assert.deepEqual(await createConversation(), summary);
  assert.deepEqual(await loadConversation(conversation), saved);
  assert.ok(fetch.mock.calls.every(call => call.arguments[1]?.credentials === "include"));
});

test("malformed timestamps do not reach transcript rendering", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({conversations: [{...summary, updated_at: "not a date"}]}));
  await assert.rejects(listConversations(), /invalid response/);
});

for (const operation of ["switch", "new", "unmount"]) {
  test(`a late response cannot update the screen after ${operation}`, async () => {
    const scope = new RequestScope();
    const first = scope.begin();
    let resolve!: (reply: string) => void;
    const pending = new Promise<string>(done => { resolve = done; });
    let visible = "second conversation";
    const update = pending.then(text => { if (scope.owns(first)) visible = text; });
    if (operation === "switch") scope.begin();
    else scope.cancel();
    resolve("late answer from the first conversation");
    await update;
    assert.equal(first.signal.aborted, true);
    assert.equal(visible, "second conversation");
    assert.equal(scope.finish(first), false);
  });
}

test("finishing an old request does not release the newer request's guard", () => {
  const scope = new RequestScope();
  const first = scope.begin();
  const second = scope.begin();
  assert.equal(scope.finish(first), false);
  assert.equal(scope.owns(second), true);
  assert.equal(scope.finish(second), true);
  assert.equal(scope.active, null);
});
