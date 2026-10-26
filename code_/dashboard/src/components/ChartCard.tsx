import { Box, Card, CardContent, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
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
  emptyText?: string;
  children: ReactNode;
};

/** Card holding one chart, its legend, and a chart/table toggle. */
export default function ChartCard({
  title,
  subtitle,
  legend = [],
  legendShape = "rect",
  table,
  empty,
  emptyText = "No calls recorded in this range yet.",
  children,
}: ChartCardProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const headingId = useId();

  return (
    <Card component="section" aria-labelledby={headingId} className="chart-card" sx={{ height: "100%" }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} sx={{ justifyContent: "space-between", alignItems: "flex-start", mb: 1.5 }}>
          <Box>
            <Typography id={headingId} variant="h3">
              {title}
            </Typography>
            {subtitle && (
              <Typography variant="body2" color="text.secondary">
                {subtitle}
              </Typography>
            )}
          </Box>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_, next: "chart" | "table" | null) => next && setView(next)}
            aria-label={`${title} view`}
          >
            <ToggleButton value="chart" sx={{ py: 0.25, px: 1.25, fontSize: 12 }}>
              Chart
            </ToggleButton>
            <ToggleButton value="table" sx={{ py: 0.25, px: 1.25, fontSize: 12 }}>
              Table
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        {view === "chart" && !empty && legend.length > 1 && (
          <Stack component="ul" direction="row" spacing={2} useFlexGap sx={{ flexWrap: "wrap", listStyle: "none", p: 0, m: "-4px 0 8px" }}>
            {legend.map((s) => (
              <Stack component="li" key={s.key} direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
                <span className={legendShape === "line" ? "line-key" : "rect-key"} style={{ background: s.color }} aria-hidden="true" />
                <Typography variant="caption" color="text.secondary">
                  {s.label}
                </Typography>
              </Stack>
            ))}
          </Stack>
        )}

        {view === "table" ? (
          <DataTable caption={title} columns={table.columns} rows={table.rows} maxHeight={216} />
        ) : empty ? (
          <Typography className="chart-empty" variant="body2" color="text.secondary">
            {emptyText}
          </Typography>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
