import assert from "node:assert/strict";
import test from "node:test";
import { answerText, measurementLabel, sourceLabel } from "../src/lib/answerPresentation.ts";
import type { Source } from "../src/lib/api.ts";

const source: Source = {
  station_id: "100093", station: "Pullman", county: "Whitman", kind: "observation",
  times: ["2026-09-29"], measurements: ["AVG_AIR_TEMP (F)", "MAX_AIR_TEMP (F)", "MIN_AIR_TEMP (F)"],
};

test("saved answers omit station references while preserving dates and weather values", () => {
  const saved = "On September 29, 2026, Pullman (station ID 100093) averaged 56.9°F, with a high of 69.2°F and low of 39.8°F.\n\nSource station: Pullman (station 100093), Whitman County.";
  assert.equal(answerText(saved, [source]),
    "On September 29, 2026, Pullman averaged 56.9°F, with a high of 69.2°F and low of 39.8°F.\n\nSource station: Pullman, Whitman County.");
});

test("model and saved reply variants do not show labeled station IDs", () => {
  for (const reference of ["(ID 100093)", "(station 100093)", "(Station ID: 100093)", "station ID 100093"]) {
    assert.doesNotMatch(answerText(`Pullman ${reference}: 56.9°F.`), /100093/);
  }
  assert.equal(answerText("Rainfall was 1.25 inches on 2026-09-29."), "Rainfall was 1.25 inches on 2026-09-29.");
});

test("source details use public names and readable measurements without mutating metadata", () => {
  const original = structuredClone(source);
  const label = sourceLabel(source);
  assert.equal(label, "Pullman, Whitman County · Observed weather · 2026-09-29 · average air temperature (°F) · high air temperature (°F) · low air temperature (°F)");
  assert.doesNotMatch(label, /100093|AVG_AIR_TEMP|MAX_AIR_TEMP|MIN_AIR_TEMP/);
  assert.deepEqual(source, original);
  assert.match(sourceLabel({...source, county: null, kind: "forecast"}), /^Pullman · Forecast/);
});

test("technical measurement names in older replies become readable text", () => {
  assert.equal(answerText("MAX_AIR_TEMP was 69.2°F and MIN_AIR_TEMP was 39.8°F.", [source]),
    "high air temperature was 69.2°F and low air temperature was 39.8°F.");
  assert.equal(measurementLabel("AVG_HUMIDITY (%)"), "average humidity (%)");
  assert.equal(measurementLabel("Temperature in °F"), "Temperature in °F");
});
