import ChartTooltip from "./ChartTooltip";
import {
  AXIS_BAND,
  MARGIN,
  PLOT_HEIGHT,
  labelIndices,
  niceTicks,
  useActiveIndex,
  useElementWidth,
  type Series,
} from "./chartUtils";

type ColumnChartProps = {
  /** Accessible name for the chart. */
  label: string;
  /** Full label per column, shown in the tooltip. */
  categories: string[];
  /** Short label per column, shown on the x axis. */
  ticks: string[];
  /** One series draws plain columns; several are stacked bottom to top in order. */
  series: Series[];
  formatValue: (value: number | null) => string;
  formatAxis?: (value: number) => string;
};

const MAX_BAR = 24;
const RADIUS = 4;
const GAP = 2; // surface gap between stacked segments

/** Column path with a rounded data end and a square base. */
function columnPath(x: number, y: number, width: number, height: number, rounded: boolean) {
  const r = rounded ? Math.min(RADIUS, height, width / 2) : 0;
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

export default function ColumnChart({ label, categories, ticks, series, formatValue, formatAxis }: ColumnChartProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const n = categories.length;
  const plotWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const band = n > 0 ? plotWidth / n : 0;
  const barWidth = Math.max(2, Math.min(MAX_BAR, band * 0.7));
  const xCenter = (i: number) => MARGIN.left + band * (i + 0.5);
  const { active, handlers } = useActiveIndex(n, xCenter);

  const totals = categories.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));
  const yTicks = niceTicks(Math.max(0, ...totals));
  const yMax = yTicks[yTicks.length - 1];
  const y = (value: number) => MARGIN.top + PLOT_HEIGHT - (value / yMax) * PLOT_HEIGHT;
  const axis = formatAxis ?? ((v: number) => formatValue(v));
  const baseline = MARGIN.top + PLOT_HEIGHT;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={MARGIN.top + PLOT_HEIGHT + AXIS_BAND}
          role="img"
          aria-label={`${label}. Use the left and right arrow keys to read values, or switch to the table view.`}
          tabIndex={0}
          {...handlers}
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? "axis-line" : "grid-line"} x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} />
              <text className="axis-text" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {axis(tick)}
              </text>
            </g>
          ))}

          {categories.map((category, i) => {
            let stackTop = baseline;
            const visible = series.filter((s) => (s.values[i] ?? 0) > 0);
            return (
              <g key={category} className={active === null || active === i ? "column" : "column column-dimmed"}>
                {visible.map((s, segment) => {
                  const value = s.values[i] ?? 0;
                  const height = Math.max(1, baseline - y(value) - (segment > 0 ? GAP : 0));
                  const top = stackTop - (segment > 0 ? GAP : 0) - height;
                  stackTop = top;
                  return (
                    <path
                      key={s.key}
                      d={columnPath(xCenter(i) - barWidth / 2, top, barWidth, height, segment === visible.length - 1)}
                      fill={s.color}
                    />
                  );
                })}
              </g>
            );
          })}

          {labelIndices(n, Math.max(2, Math.floor(plotWidth / 64))).map((i) => (
            <text key={i} className="axis-text" x={xCenter(i)} y={baseline + 18} textAnchor="middle">
              {ticks[i]}
            </text>
          ))}
        </svg>
      )}
      {active !== null && (
        <ChartTooltip
          title={categories[active]}
          series={series}
          index={active}
          x={xCenter(active)}
          width={width}
          formatValue={formatValue}
          total={series.length > 1 ? formatValue(totals[active]) : undefined}
        />
      )}
    </div>
  );
}
