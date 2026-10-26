/** Number and date formatting shared by tiles, charts, and tables. */

const EMPTY = "—";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const grouped = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const compactUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

/** Dollars, keeping two significant digits below $1 so small per call and per user costs stay distinguishable. */
export function formatUsd(value: number | null | undefined): string {
  if (value == null) return EMPTY;
  if (value === 0) return "$0.00";
  const abs = Math.abs(value);
  if (abs < 0.000001) return value < 0 ? "-<$0.000001" : "<$0.000001";
  if (abs < 1) return `${value < 0 ? "-" : ""}$${abs.toPrecision(2)}`;
  if (abs >= 10_000) return compactUsd.format(value);
  return usd.format(value);
}

/** Counts: 5,878 below ten thousand, 12.9K above. */
export function formatCount(value: number | null | undefined): string {
  if (value == null) return EMPTY;
  return Math.abs(value) >= 10_000 ? compact.format(value) : grouped.format(value);
}

/** A 0-1 ratio as a percentage, one decimal below 10%. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) return EMPTY;
  const percent = value * 100;
  return `${percent > 0 && percent < 10 ? percent.toFixed(1) : Math.round(percent)}%`;
}

/** Milliseconds as "850 ms", "1.8 s", or "5 s". */
export function formatMs(value: number | null | undefined): string {
  if (value == null) return EMPTY;
  return value < 1000 ? `${Math.round(value)} ms` : `${Number((value / 1000).toFixed(1))} s`;
}

/** Averages such as sessions per user. */
export function formatDecimal(value: number | null | undefined): string {
  if (value == null) return EMPTY;
  return value.toFixed(1);
}

/** Relative change from `previous` to `current`, or null when there is no baseline. */
export function relativeChange(current: number | null, previous: number | null): number | null {
  if (current == null || previous == null || previous === 0) return null;
  return (current - previous) / previous;
}

/** Parse a YYYY-MM-DD bucket as a local calendar date (no timezone shift). */
export function parseBucket(bucket: string): Date {
  const [year, month, day] = bucket.split("-").map(Number);
  return new Date(year, month - 1, day);
}

const dayLabel = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const monthLabel = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" });

export function formatBucket(bucket: string, unit: "day" | "week" | "month"): string {
  const date = parseBucket(bucket);
  if (unit === "month") return monthLabel.format(date);
  return unit === "week" ? `Week of ${dayLabel.format(date)}` : dayLabel.format(date);
}

/** Short axis tick label for a bucket. */
export function formatBucketTick(bucket: string, unit: "day" | "week" | "month"): string {
  const date = parseBucket(bucket);
  if (unit !== "month") return dayLabel.format(date);
  // include the year so a 12 month range that starts and ends in the same month stays unambiguous
  return `${new Intl.DateTimeFormat("en-US", { month: "short" }).format(date)} ’${String(date.getFullYear()).slice(2)}`;
}
