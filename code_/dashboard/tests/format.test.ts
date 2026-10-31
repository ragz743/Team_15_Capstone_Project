import assert from "node:assert/strict";
import { test } from "node:test";
import { formatBucket, formatBucketTick, formatCount, formatMs, formatPercent, formatUsd, relativeChange } from "../src/format.ts";

test("formats dollars with enough precision for sub-cent call costs", () => {
  assert.equal(formatUsd(null), "—");
  assert.equal(formatUsd(0), "$0.00");
  assert.equal(formatUsd(0.0000004), "<$0.000001");
  assert.equal(formatUsd(0.000093), "$0.000093");
  assert.equal(formatUsd(0.00037151), "$0.00037");
  assert.equal(formatUsd(0.01935122), "$0.019");
  assert.equal(formatUsd(0.5), "$0.50");
  assert.equal(formatUsd(2.18377), "$2.18");
  assert.equal(formatUsd(48_250), "$48.3K");
});

test("formats counts, percentages, and durations", () => {
  assert.equal(formatCount(5878), "5,878");
  assert.equal(formatCount(23_459), "23.5K");
  assert.equal(formatPercent(0.0144), "1.4%");
  assert.equal(formatPercent(0.2), "20%");
  assert.equal(formatPercent(0), "0%");
  assert.equal(formatMs(850.4), "850 ms");
  assert.equal(formatMs(3309.4), "3.3 s");
  assert.equal(formatMs(5000), "5 s");
});

test("relative change needs a non-zero baseline", () => {
  assert.equal(relativeChange(15, 10), 0.5);
  assert.equal(relativeChange(5, 0), null);
  assert.equal(relativeChange(null, 10), null);
});

test("bucket dates are read as local calendar dates", () => {
  assert.equal(formatBucket("2026-10-01", "month"), "Oct 2026");
  assert.equal(formatBucket("2026-10-14", "day"), "Oct 14");
  assert.equal(formatBucket("2026-10-12", "week"), "Week of Oct 12");
  assert.equal(formatBucketTick("2025-10-01", "month"), "Oct ’25");
});
