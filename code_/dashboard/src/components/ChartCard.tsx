import { useId, useState, type ReactNode } from "react";
import DataTable, { type Column } from "./DataTable";
import type { Series } from "./chartUtils";

type ChartCardProps = {
  title: string;
  subtitle?: string;
  /** Series drawn by the chart; a legend appears when there are two or more. */
  legend?: Pick<Series, "key" | "label" | "color">[];
  legendShape?: "rect" | "line";
  table: { columns: Column[]; rows: Record<string, ReactNode>[] };
  /** True when every value is empty, so the chart is replaced by a short note. */
  empty?: boolean;
  children: ReactNode;
};

/** Card holding one chart, its legend, and a chart/table toggle. */
export default function ChartCard({ title, subtitle, legend = [], legendShape = "rect", table, empty, children }: ChartCardProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const headingId = useId();

  return (
    <section className="card chart-card" aria-labelledby={headingId}>
      <header className="card-header">
        <div>
          <h3 id={headingId}>{title}</h3>
          {subtitle && <p className="card-subtitle">{subtitle}</p>}
        </div>
        <div className="view-toggle" role="group" aria-label={`${title} view`}>
          {(["chart", "table"] as const).map((option) => (
            <button key={option} type="button" aria-pressed={view === option} onClick={() => setView(option)}>
              {option === "chart" ? "Chart" : "Table"}
            </button>
          ))}
        </div>
      </header>

      {view === "chart" && !empty && legend.length > 1 && (
        <ul className="legend">
          {legend.map((s) => (
            <li key={s.key}>
              <span className={legendShape === "line" ? "line-key" : "rect-key"} style={{ background: s.color }} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
      )}

      {view === "table" ? (
        <DataTable caption={title} columns={table.columns} rows={table.rows} />
      ) : empty ? (
        <p className="chart-empty">No requests recorded in this range yet.</p>
      ) : (
        children
      )}
    </section>
  );
}
