import type { Series } from "./chartUtils";

type ChartTooltipProps = {
  title: string;
  series: Series[];
  index: number;
  x: number;
  width: number;
  formatValue: (value: number | null) => string;
  total?: string;
};

const TOOLTIP_WIDTH = 176;

/** One readout listing every series at the active x position; values lead, labels follow. */
export default function ChartTooltip({ title, series, index, x, width, formatValue, total }: ChartTooltipProps) {
  // keep the tooltip inside the chart, flipping to the left of the crosshair near the right edge
  const left = x + 12 + TOOLTIP_WIDTH > width ? Math.max(0, x - 12 - TOOLTIP_WIDTH) : x + 12;
  return (
    <div className="chart-tooltip" style={{ left, width: TOOLTIP_WIDTH }} role="status" aria-live="polite">
      <div className="chart-tooltip-title">{title}</div>
      {series.map((s) => (
        <div className="chart-tooltip-row" key={s.key}>
          <span className="line-key" style={{ background: s.color }} aria-hidden="true" />
          <strong>{formatValue(s.values[index])}</strong>
          <span className="chart-tooltip-label">{s.label}</span>
        </div>
      ))}
      {total && (
        <div className="chart-tooltip-row chart-tooltip-total">
          <strong>{total}</strong>
          <span className="chart-tooltip-label">Total</span>
        </div>
      )}
    </div>
  );
}
