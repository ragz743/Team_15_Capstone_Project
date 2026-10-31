import assert from "node:assert/strict";
import { test } from "node:test";
import { conversationReducer, initialState, type Message } from "../src/lib/conversationState.ts";
import { sendSavedChat, type SavedChatResponse, type SavedConversation } from "../src/lib/api.ts";

const point = { latitude: 46.73, longitude: -117.18 };
const otherPoint = { latitude: 47.2, longitude: -120.5 };
const conversation = "11111111-1111-4111-8111-111111111111";
const request = "22222222-2222-4222-8222-222222222222";
const timestamp = "2026-09-10T18:00:00Z";
const message: Message = { id: `${request}:user`, role: "user", text: "Wind?", timestamp, requestId: request, point };
const context = { station_ids: ["1"], county: null, start: "2026-09-10", end: "2026-09-10", subject: "wind", point };
const savedReply: SavedChatResponse = {
  reply: "Fresh weather at the saved location",
  model: "test",
  context,
  conversation_id: conversation,
  request_id: request,
  outcome: "success",
};
const saved: SavedConversation = {
  id: conversation,
  title: "Wind?",
  created_at: timestamp,
  updated_at: timestamp,
  context,
  next_before: 2,
  messages: [
    {
      id: message.id,
      request_id: request,
      role: "user",
      content: message.text,
      created_at: timestamp,
      status: "failed",
      request_input: { point },
    },
  ],
};

test("a failed request retains its submitted point when the map changes", () => {
  let state = conversationReducer(initialState, { type: "sending", message });
  state = conversationReducer(state, { type: "failed", requestId: request, error: "Try again" });
  state = conversationReducer(state, { type: "point", value: otherPoint });
  const original = state.messages.find((item) => item.role === "user")!;
  assert.deepEqual(original.point, point);
  state = conversationReducer(state, { type: "sending", message: original });
  assert.equal(state.messages.length, 2);
  assert.equal(state.messages[0].status, "pending");
  assert.deepEqual(state.messages[0].point, point);
  state = conversationReducer(state, { type: "answered", result: savedReply, text: message.text });
  assert.deepEqual(state.point, otherPoint);
  assert.deepEqual(state.pendingPoint, otherPoint);
});

test("restoration recovers the map and the exact retry input", () => {
  const state = conversationReducer(initialState, { type: "loaded", chat: saved });
  assert.deepEqual(state.point, point);
  assert.deepEqual(state.messages[0].point, point);
  assert.equal(state.messages[0].requestId, request);
  assert.deepEqual(state.pendingPoint, point);
});

test("earlier messages cannot replace the active map point or draft", () => {
  const state = { ...initialState, point: otherPoint, pendingPoint: otherPoint, draft: "Keep my draft" };
  const result = conversationReducer(state, { type: "loaded", chat: saved, older: true });
  assert.deepEqual(result.point, otherPoint);
  assert.equal(result.draft, "Keep my draft");
  assert.deepEqual(result.pendingPoint, otherPoint);
});

test("a new conversation clears location without discarding saved history", () => {
  const state = { ...initialState, point, pendingPoint: point, conversations: [saved], messages: [message] };
  const result = conversationReducer(state, { type: "new" });
  assert.equal(result.point, null);
  assert.equal(result.pendingPoint, null);
  assert.equal(result.messages.length, 0);
  assert.equal(result.conversations.length, 1);
});

test("pagination does not duplicate a conversation that changed pages", () => {
  const state = { ...initialState, conversations: [saved] };
  const result = conversationReducer(state, { type: "list", items: [saved], older: true });
  assert.equal(result.conversations.length, 1);
});

test("sending and retrying use the same selected point", async (t) => {
  const result = {
    reply: "Saved weather",
    model: "test",
    context,
    conversation_id: conversation,
    request_id: request,
    outcome: "success",
  };
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(result));
  await sendSavedChat(conversation, request, "Wind?", undefined, point);
  await sendSavedChat(conversation, request, "Wind?", undefined, point);
  const bodies = fetch.mock.calls.map((call) => JSON.parse(String(call.arguments[1]?.body)));
  assert.deepEqual(bodies[0], bodies[1]);
  assert.deepEqual(bodies[0].point, point);
});

test("reusing a saved location replaces the current map point", () => {
  const state = { ...initialState, point: otherPoint };
  const result = conversationReducer(state, {
    type: "answered",
    text: "Use the location from our previous conversation",
    result: savedReply,
  });
  assert.deepEqual(result.point, point);
});

test("reload does not turn a saved point into a new selection", () => {
  const chat: SavedConversation = {
    ...saved,
    messages: saved.messages.map((message) => ({ ...message, status: "completed" })),
  };
  const state = conversationReducer(initialState, { type: "loaded", chat });
  assert.deepEqual(state.point, point);
  assert.equal(state.pendingPoint, null);
});

test("a selected point remains pending until the server accepts it", () => {
  const selected = conversationReducer(initialState, { type: "point", value: point });
  assert.deepEqual(selected.pendingPoint, point);
  const answered = conversationReducer(selected, { type: "answered", result: savedReply, text: message.text });
  assert.deepEqual(answered.point, point);
  assert.equal(answered.pendingPoint, null);
});

test("recalling an answer preserves an unused map selection", () => {
  const selected = conversationReducer(initialState, { type: "point", value: otherPoint });
  const state = conversationReducer(selected, {
    type: "answered",
    result: { ...savedReply, outcome: "history" },
    text: "What did we discuss last time?",
  });
  assert.deepEqual(state.point, otherPoint);
  assert.deepEqual(state.pendingPoint, otherPoint);
});


test("recall mode survives a failed turn and reload while new chats default to weather", () => {
  const recalled: SavedConversation = { ...saved, messages: saved.messages.map((item) => ({
    ...item, request_input: { point, mode: "history" },
  })) };
  let state = conversationReducer(initialState, { type: "loaded", chat: recalled });
  assert.equal(state.mode, "history");
  state = conversationReducer(state, { type: "mode", value: "weather" });
  assert.equal(state.messages[0].mode, "history");
  assert.equal(conversationReducer(state, { type: "new" }).mode, "weather");
});

test("the saved request sends the selected operation", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(savedReply));
  await sendSavedChat(conversation, request, "Remember?", undefined, null, "history");
  assert.equal(JSON.parse(String(fetch.mock.calls[0].arguments[1]?.body)).mode, "history");
});


test("source details survive an answer and a saved conversation reload", () => {
  const metadata = { coverage: "subset" as const, sources: [{
    station_id: "1", station: "Pullman", county: "Whitman", kind: "observation" as const,
    times: ["2026-09-29"], measurements: ["AVG_AIR_TEMP (F)"],
  }] };
  let state = conversationReducer(initialState, { type: "sending", message });
  state = conversationReducer(state, { type: "answered", result: { ...savedReply, ...metadata }, text: message.text });
  assert.deepEqual(state.messages[1].metadata, metadata);
  const restored: SavedConversation = { ...saved, messages: [{ ...saved.messages[0], role: "assistant", metadata }] };
  state = conversationReducer(initialState, { type: "loaded", chat: restored });
  assert.deepEqual(state.messages[0].metadata, metadata);
});
