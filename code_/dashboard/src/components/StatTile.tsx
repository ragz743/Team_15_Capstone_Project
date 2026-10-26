import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import { Card, CardContent, Stack, Typography } from "@mui/material";
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
};

/** A labelled number with an optional change versus the previous period. */
export default function StatTile({ label, value, current = null, previous = null, upIsGood = null, periodLabel, hint }: StatTileProps) {
  const change = relativeChange(current, previous);
  let color = "text.secondary";
  if (change !== null && change !== 0 && upIsGood !== null) {
    color = change > 0 === upIsGood ? "success.dark" : "error.dark";
  }
  const Icon = change === null || change === 0 ? TrendingFlatIcon : change > 0 ? TrendingUpIcon : TrendingDownIcon;

  return (
    <Card className="stat-tile" sx={{ height: "100%" }}>
      <CardContent sx={{ "&:last-child": { pb: 2 } }}>
        <Typography className="stat-label" variant="body2" color="text.secondary">
          {label}
        </Typography>
        <Typography className="stat-value" component="div" sx={{ fontSize: 26, fontWeight: 600, lineHeight: 1.25 }}>
          {value}
        </Typography>
        {change !== null ? (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: "center", color }}>
            <Icon sx={{ fontSize: 16 }} aria-hidden />
            <Typography variant="caption" color="inherit">
              <span className="visually-hidden">{change > 0 ? "Up" : change < 0 ? "Down" : "No change"} </span>
              {formatPercent(Math.abs(change))} vs previous {periodLabel}
            </Typography>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.secondary">
            No earlier data to compare
          </Typography>
        )}
        {hint && (
          <Typography className="stat-hint" variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
            {hint}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
