import CancelIcon from "@mui/icons-material/Cancel";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import { Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { formatPercent } from "../format";
import type { Metrics } from "../types";
import ChartCard from "./ChartCard";
import DataTable from "./DataTable";
import LineChart from "./LineChart";
import type { Series } from "./chartUtils";

const runDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const runDateTime = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const SOURCE_LABELS = { current: "Current conditions", historical: "Past 7 days", forecast: "Forecast" } as const;

const percentAxis = (v: number) => `${Math.round(v * 100)}%`;

/** Sampled retrieval quality: the score of each scheduled run, and the latest run question by question. */
export default function QualityPanel({ quality }: { quality: Metrics["quality"] }) {
  const runs = quality.runs;
  const latest = quality.latest;
  const scoreSeries: Series[] = [{ key: "score", label: "Score", color: "var(--series-1)", values: runs.map((r) => r.score) }];

  return (
    <Stack spacing={2}>
      <ChartCard
        title="Retrieval quality"
        subtitle="Share of sample questions where the right weather data was found, checked once a day"
        empty={runs.length === 0}
        emptyText="No quality checks ran in this range. The API runs one daily; python -m scripts.evaluate_retrieval runs one now."
        table={{
          columns: [
            { key: "date", label: "Run" },
            { key: "score", label: "Score", numeric: true },
            { key: "passed", label: "Passed", numeric: true },
          ],
          rows: runs.map((r) => ({
            date: runDateTime.format(new Date(r.run_at)),
            score: formatPercent(r.score),
            passed: `${r.passed} of ${r.samples}`,
          })),
        }}
      >
        <LineChart
          label="Retrieval quality score by run"
          categories={runs.map((r) => runDateTime.format(new Date(r.run_at)))}
          ticks={runs.map((r) => runDate.format(new Date(r.run_at)))}
          series={scoreSeries}
          formatValue={formatPercent}
          formatAxis={percentAxis}
          target={{ value: 1, label: "All questions" }}
        />
      </ChartCard>

      <Card component="section" aria-labelledby="quality-latest-heading">
        <CardContent>
          <Typography id="quality-latest-heading" variant="h3">
            Latest check
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {latest
              ? `${latest.passed} of ${latest.samples} questions passed on ${runDateTime.format(new Date(latest.run_at))}`
              : "No quality check has run yet"}
          </Typography>
          {latest && (
            <DataTable
              caption="Latest retrieval quality check"
              columns={[
                { key: "result", label: "Result" },
                { key: "question", label: "Question" },
                { key: "data", label: "Data" },
                { key: "found", label: "Found" },
              ]}
              rows={latest.details.map((d) => ({
                result: (
                  <Chip
                    size="small"
                    variant="outlined"
                    color={d.passed ? "success" : "error"}
                    icon={d.passed ? <CheckCircleIcon /> : <CancelIcon />}
                    label={d.passed ? "Found" : "Missed"}
                  />
                ),
                question: <span className="wrap-cell">{d.question}</span>,
                data: `${SOURCE_LABELS[d.source]} · ${d.expected}`,
                found: d.error ? `Error: ${d.error}` : d.found.join(", ") || "Nothing",
              }))}
            />
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
