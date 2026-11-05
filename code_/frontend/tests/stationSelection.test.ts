import assert from "node:assert/strict";
import { test } from "node:test";
import { listStations, nearbyStations, sendSavedChat, type SavedChatResponse, type SavedConversation } from "../src/lib/api.ts";
import { conversationReducer, initialState, type Message } from "../src/lib/conversationState.ts";

const conversation = "11111111-1111-4111-8111-111111111111";
const request = "22222222-2222-4222-8222-222222222222";
const timestamp = "2026-09-30T18:00:00Z";
const message: Message = {
  id: `${request}:user`, requestId: request, role: "user", text: "Temperature?", timestamp, stationId: "1",
};
const reply: SavedChatResponse = {
  conversation_id: conversation, request_id: request, outcome: "success", reply: "70 F", model: "fixture",
  context: { station_ids: ["1"], county: null, start: null, end: null, subject: null, point: null },
};

test("station retries keep their original selection when the picker changes", () => {
  let state = conversationReducer(initialState, { type: "station", value: "1" });
  state = conversationReducer(state, { type: "sending", message });
  state = conversationReducer(state, { type: "failed", requestId: request, error: "Try again" });
  state = conversationReducer(state, { type: "station", value: "2" });
  assert.equal(state.messages[0].stationId, "1");
  state = conversationReducer(state, { type: "answered", result: reply, text: message.text });
  assert.equal(state.stationId, "2");
  assert.equal(state.pendingStationId, "2");
  assert.equal(state.point, null);
});

test("reloading restores failed station input and completed station context", () => {
  const saved: SavedConversation = {
    id: conversation, title: "Weather", created_at: timestamp, updated_at: timestamp,
    context: reply.context, next_before: null,
    messages: [{ id: message.id, request_id: request, role: "user", content: message.text,
      created_at: timestamp, status: "failed", request_input: { station_id: "2" } }],
  };
  let state = conversationReducer(initialState, { type: "loaded", chat: saved });
  assert.equal(state.stationId, "2");
  assert.equal(state.pendingStationId, "2");
  assert.equal(state.messages[0].stationId, "2");
  saved.messages[0].status = "completed";
  state = conversationReducer(state, { type: "loaded", chat: saved });
  assert.equal(state.stationId, "1");
  assert.equal(state.pendingStationId, null);
  assert.equal(conversationReducer(state, { type: "new" }).stationId, null);
});

test("station selection replaces old coordinates and remains pending during recall", () => {
  const state = { ...initialState, point: { latitude: 47, longitude: -117 }, pendingPoint: { latitude: 47, longitude: -117 } };
  const selected = conversationReducer(state, { type: "station", value: "2" });
  assert.equal(selected.point, null);
  assert.equal(selected.pendingPoint, null);
  const recalled = conversationReducer(selected, { type: "answered", result: { ...reply, outcome: "history" }, text: "Recall" });
  assert.equal(recalled.stationId, "2");
  assert.equal(recalled.pendingStationId, "2");
});

test("accepted station selection is reused by followups without a new selection", () => {
  const selected = conversationReducer(initialState, { type: "station", value: "1" });
  const state = conversationReducer(selected, { type: "answered", result: reply, text: message.text });
  assert.equal(state.stationId, "1");
  assert.equal(state.pendingStationId, null);
});

test("saved station requests send an ID without device coordinates", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(reply));
  await sendSavedChat(conversation, request, message.text, undefined, null, "weather", "1");
  const sent = JSON.parse(String(fetch.mock.calls[0].arguments[1]?.body));
  assert.equal(sent.station_id, "1");
  assert.equal(sent.point, undefined);
});

const catalog = {
  stations: [{ id: "1", name: "Pullman", county: "Whitman", distance_km: 1.2 }],
  counties: ["Whitman"], located_count: 1,
};

test("nearby requests send coordinates only to the station sorting endpoint", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(catalog));
  const point = { latitude: 46.7, longitude: -117.1 };
  assert.deepEqual(await nearbyStations(point), catalog);
  assert.equal(fetch.mock.calls[0].arguments[0], "/api/stations/nearby");
  assert.deepEqual(JSON.parse(String(fetch.mock.calls[0].arguments[1]?.body)), point);
});

test("station catalog rejects coordinates and conflicting IDs in public responses", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    ...catalog, stations: [{ ...catalog.stations[0], latitude: 46.7 }],
  }));
  await assert.rejects(listStations());
  fetch.mock.mockImplementation(async () => Response.json({ ...catalog, stations: [catalog.stations[0], catalog.stations[0]] }));
  await assert.rejects(listStations());
});
