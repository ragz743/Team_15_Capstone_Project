import { formatPercent, relativeChange } from "../format";

type StatTileProps = {
  label: string;
  value: string;
  current?: number | null;
  previous?: number | null;
  /** Whether an increase is good (true), bad (false), or neither (null). */
  upIsGood?: boolean | null;
  periodLabel: string;
  hint?: string;
  hero?: boolean;
};

/** A labelled number with an optional change versus the previous period. */
export default function StatTile({
  label,
  value,
  current = null,
  previous = null,
  upIsGood = null,
  periodLabel,
  hint,
  hero = false,
}: StatTileProps) {
  const change = relativeChange(current, previous);
  let tone = "neutral";
  if (change !== null && change !== 0 && upIsGood !== null) {
    tone = change > 0 === upIsGood ? "good" : "bad";
  }

  return (
    <div className={hero ? "card stat-tile stat-tile-hero" : "card stat-tile"}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {change !== null ? (
        <div className={`stat-delta stat-delta-${tone}`}>
          <span aria-hidden="true">{change > 0 ? "▲" : change < 0 ? "▼" : "■"}</span>
          <span className="visually-hidden">{change > 0 ? "Up" : change < 0 ? "Down" : "No change"}</span>{" "}
          {formatPercent(Math.abs(change))} vs previous {periodLabel}
        </div>
      ) : (
        <div className="stat-delta stat-delta-neutral">No earlier data to compare</div>
      )}
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
