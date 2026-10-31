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

type LineChartProps = {
  label: string;
  categories: string[];
  ticks: string[];
  series: Series[];
  formatValue: (value: number | null) => string;
  formatAxis?: (value: number) => string;
  /** A horizontal reference line, e.g. a response time target. */
  target?: { value: number; label: string };
};

const END_LABEL_SPACE = 36;
const MIN_LABEL_GAP = 14;

/** Split a series into runs of consecutive non-null points so gaps in the data stay gaps. */
function segments(values: (number | null)[]) {
  const runs: number[][] = [];
  let run: number[] = [];
  values.forEach((value, i) => {
    if (value == null) {
      if (run.length) runs.push(run);
      run = [];
    } else {
      run.push(i);
    }
  });
  if (run.length) runs.push(run);
  return runs;
}

export default function LineChart({ label, categories, ticks, series, formatValue, formatAxis, target }: LineChartProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const n = categories.length;
  const right = MARGIN.right + END_LABEL_SPACE;
  const plotWidth = Math.max(0, width - MARGIN.left - right);
  const x = (i: number) => MARGIN.left + (n > 1 ? (plotWidth * i) / (n - 1) : plotWidth / 2);
  const { active, handlers } = useActiveIndex(n, x);

  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const yTicks = niceTicks(Math.max(0, ...values, target?.value ?? 0));
  const yMax = yTicks[yTicks.length - 1];
  const y = (value: number) => MARGIN.top + PLOT_HEIGHT - (value / yMax) * PLOT_HEIGHT;
  const axis = formatAxis ?? ((v: number) => formatValue(v));
  const baseline = MARGIN.top + PLOT_HEIGHT;

  // direct end labels only when they cannot collide; otherwise the legend and tooltip carry identity
  const ends = series.map((s) => {
    const last = s.values.findLastIndex((v) => v != null);
    return last < 0 ? null : { key: s.key, label: s.endLabel ?? s.label, i: last, y: y(s.values[last] as number) };
  });
  const endYs = ends.filter((e) => e !== null).map((e) => e.y).sort((a, b) => a - b);
  const labelEnds = endYs.every((v, i) => i === 0 || v - endYs[i - 1] >= MIN_LABEL_GAP);

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
              <line className={tick === 0 ? "axis-line" : "grid-line"} x1={MARGIN.left} x2={width - right} y1={y(tick)} y2={y(tick)} />
              <text className="axis-text" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {axis(tick)}
              </text>
            </g>
          ))}

          {target && (
            <g>
              <line className="target-line" x1={MARGIN.left} x2={width - right} y1={y(target.value)} y2={y(target.value)} />
              <text className="target-label" x={MARGIN.left + 6} y={y(target.value) - 5}>
                {target.label}
              </text>
            </g>
          )}

          {active !== null && <line className="crosshair" x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={baseline} />}

          {series.map((s) =>
            segments(s.values).map((run) => (
              <polyline
                key={`${s.key}-${run[0]}`}
                className="series-line"
                stroke={s.color}
                points={run.map((i) => `${x(i)},${y(s.values[i] as number)}`).join(" ")}
              />
            )),
          )}

          {series.map((s, si) => {
            const end = ends[si];
            const points = active !== null && s.values[active] != null ? [active] : [];
            if (end && !points.includes(end.i)) points.push(end.i);
            return points.map((i) => (
              <circle key={`${s.key}-dot-${i}`} className="series-dot" cx={x(i)} cy={y(s.values[i] as number)} r={4} fill={s.color} />
            ));
          })}

          {labelEnds &&
            ends.map(
              (end) =>
                end && (
                  <text key={end.key} className="end-label" x={x(end.i) + 8} y={end.y} dy="0.32em">
                    {end.label}
                  </text>
                ),
            )}

          {labelIndices(n, Math.max(2, Math.floor(plotWidth / 64))).map((i) => (
            <text key={i} className="axis-text" x={x(i)} y={baseline + 18} textAnchor="middle">
              {ticks[i]}
            </text>
          ))}
        </svg>
      )}
      {active !== null && (
        <ChartTooltip title={categories[active]} series={series} index={active} x={x(active)} width={width} formatValue={formatValue} />
      )}
    </div>
  );
}
