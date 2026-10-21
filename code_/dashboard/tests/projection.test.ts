import assert from "node:assert/strict";
import { test } from "node:test";
import { projectMonth, scaleBasis } from "../src/projection.ts";
import type { MonthPoint } from "../src/types.ts";

function month(bucket: string, users: number, costPerUser: number | null, calls: number, partial = false): MonthPoint {
  return {
    bucket, users, partial, avg_cost_per_user: costPerUser, llm_calls: calls,
    requests: 0, failed_requests: 0, error_rate: null, avg_sessions_per_user: null, chat_calls: 0,
    embedding_calls: 0, cost_usd: 0, latency_p50_ms: null, latency_p95_ms: null,
  };
}

test("averages per user cost over complete months, weighted by users", () => {
  const basis = scaleBasis([
    month("2026-08-01", 100, 0.01, 4_000),
    month("2026-09-01", 300, 0.02, 12_000),
    month("2026-10-01", 50, 0.5, 9_000, true), // partial month is ignored
  ]);
  assert.ok(basis);
  assert.equal(basis.months, 2);
  assert.equal(basis.usesPartialMonth, false);
  assert.ok(Math.abs(basis.costPerUser - (100 * 0.01 + 300 * 0.02) / 400) < 1e-12);
  assert.equal(basis.callsPerUser, 40);

  const projected = projectMonth(basis, 10_000);
  assert.ok(Math.abs(projected.cost - 175) < 1e-9);
  assert.equal(projected.calls, 400_000);
});

test("falls back to the partial month, and to nothing without users", () => {
  const partialOnly = scaleBasis([month("2026-10-01", 20, 0.03, 600, true)]);
  assert.equal(partialOnly?.usesPartialMonth, true);
  assert.equal(scaleBasis([month("2026-10-01", 0, null, 0, true)]), null);
  assert.equal(scaleBasis([]), null);
});
