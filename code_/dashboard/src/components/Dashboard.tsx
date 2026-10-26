import { Alert, Card, CardContent, Grid, Typography } from "@mui/material";
import { Children, type ReactNode } from "react";
import { formatBucket, formatBucketTick, formatCount, formatDecimal, formatMs, formatPercent, formatUsd } from "../format";
import type { Metrics, RangeKey } from "../types";
import BudgetCard from "./BudgetCard";
import ChartCard from "./ChartCard";
import ColumnChart from "./ColumnChart";
import DataTable from "./DataTable";
import LineChart from "./LineChart";
import QualityPanel from "./QualityPanel";
import StatTile from "./StatTile";
import UserCostTable from "./UserCostTable";
import type { Series } from "./chartUtils";

const STATUS_LABELS: Record<string, string> = {
  ok: "Answered",
  empty: "Empty answer",
  error: "Error",
  rate_limited: "Rate limited by provider",
  unavailable: "Service unavailable",
};

const COST_SOURCE_LABELS: Record<string, string> = {
  billed: "Actual (reported by provider)",
  estimated: "Estimated from tokens",
  mixed: "Partly actual, partly estimated",
  unpriced: "No price set",
};

const periodLabels: Record<number, string> = { 7: "7 days", 30: "30 days", 90: "90 days", 365: "12 months" };

const count = (v: number | null) => formatCount(v);
const msAxis = (v: number) => (v === 0 ? "0" : formatMs(v));
const percentAxis = (v: number) => `${Number((v * 100).toFixed(1))}%`;
const usdAxis = (v: number) => (v === 0 ? "$0" : formatUsd(v));
const runDay = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

function SectionHeading({ id, children }: { id: string; children: ReactNode }) {
  return (
    <Typography id={id} variant="h2" sx={{ mt: 4, mb: 1.5 }}>
      {children}
    </Typography>
  );
}

/** KPI tiles: four across on wide screens, two on tablets and phones. */
function TileGrid({ children }: { children: ReactNode }) {
  return (
    <Grid container spacing={1.5}>
      {Children.map(children, (child) => child && <Grid size={{ xs: 6, lg: 3 }}>{child}</Grid>)}
    </Grid>
  );
}

/** A row of equal width chart cards that stacks on narrow screens. */
function ChartRow({ columns = 2, children }: { columns?: 2 | 3; children: ReactNode }) {
  return (
    <Grid container spacing={2}>
      {Children.map(children, (child) => child && <Grid size={{ xs: 12, md: 6, lg: 12 / columns }}>{child}</Grid>)}
    </Grid>
  );
}

/** A full width card with a heading, used for tables. */
function TableCard({ id, title, subtitle, children }: { id: string; title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Card component="section" aria-labelledby={id} sx={{ mt: 2 }}>
      <CardContent>
        <Typography id={id} variant="h3">
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {subtitle}
          </Typography>
        )}
        {children}
      </CardContent>
    </Card>
  );
}

type DashboardProps = { metrics: Metrics; range: RangeKey; token: string; refreshCount: number };

export default function Dashboard({ metrics, range: rangeKey, token, refreshCount }: DashboardProps) {
  const { summary, previous, series, range, quality } = metrics;
  const period = periodLabels[range.days] ?? `${range.days} days`;
  const unit = range.bucket;
  const empty = summary.calls === 0;
  const target = formatMs(metrics.target_ms);
  const latestQuality = quality.latest;
  const previousRun = quality.runs.length > 1 ? quality.runs[quality.runs.length - 2] : null;

  const categories = series.map((p) => formatBucket(p.bucket, unit));
  const ticks = series.map((p) => formatBucketTick(p.bucket, unit));
  const one = (key: string, label: string, values: (number | null)[]): Series[] => [
    { key, label, color: "var(--series-1)", values },
  ];

  const usersSeries = one("users", "Active users", series.map((p) => p.users));
  const sessionSeries = one("sessions", "Successful sessions", series.map((p) => p.successful_session_rate));
  const callsSeries = one("calls", "Calls", series.map((p) => p.calls));
  const costSeries = one("cost", "LLM spending", series.map((p) => p.cost_usd));
  const withinTargetSeries = one("within", `Answered within ${target}`, series.map((p) => p.within_target_rate));
  const errorSeries = one("errors", "Failed calls", series.map((p) => p.error_rate));
  const latencySeries: Series[] = [
    { key: "p50", label: "Median", endLabel: "p50", color: "var(--series-1)", values: series.map((p) => p.latency_p50_ms) },
    { key: "p95", label: "95th percentile", endLabel: "p95", color: "var(--series-2)", values: series.map((p) => p.latency_p95_ms) },
  ];

  const unpriced = metrics.by_model.filter((m) => !m.priced);
  const dateColumn = { key: "date", label: unit === "day" ? "Date" : unit === "week" ? "Week" : "Month" };

  return (
    <>
      <section aria-labelledby="overview-heading">
        <SectionHeading id="overview-heading">Overview</SectionHeading>
        <TileGrid>
          <StatTile
            label="Active users"
            value={formatCount(summary.users)}
            current={summary.users}
            previous={previous.users}
            upIsGood
            periodLabel={period}
            hint="Logged-in users who used the chatbot"
          />
          <StatTile
            label="Successful sessions"
            value={formatPercent(summary.successful_session_rate)}
            current={summary.successful_session_rate}
            previous={previous.successful_session_rate}
            upIsGood
            periodLabel={period}
            hint={`${formatCount(summary.successful_sessions)} of ${formatCount(summary.sessions)} login sessions`}
          />
          <StatTile
            label="Retrieval quality"
            value={formatPercent(latestQuality?.score)}
            current={latestQuality?.score ?? null}
            previous={previousRun?.score ?? null}
            upIsGood
            periodLabel="check"
            hint={
              latestQuality
                ? `${latestQuality.passed} of ${latestQuality.samples} sample questions · ${runDay.format(new Date(latestQuality.run_at))}`
                : "No check has run yet"
            }
          />
          <StatTile
            label="Calls"
            value={formatCount(summary.calls)}
            current={summary.calls}
            previous={previous.calls}
            periodLabel={period}
            hint={`${formatDecimal(summary.avg_calls_per_session)} calls per session`}
          />
          <StatTile
            label={`Answered within ${target}`}
            value={formatPercent(summary.within_target_rate)}
            current={summary.within_target_rate}
            previous={previous.within_target_rate}
            upIsGood
            periodLabel={period}
            hint={`Median ${formatMs(summary.latency_p50_ms)} · 95th percentile ${formatMs(summary.latency_p95_ms)}`}
          />
          <StatTile
            label="LLM spending"
            value={formatUsd(summary.cost_usd)}
            current={summary.cost_usd}
            previous={previous.cost_usd}
            periodLabel={period}
            hint={`${formatUsd(summary.avg_cost_per_user)} per active user`}
          />
          <StatTile
            label="Cost per 1,000 calls"
            value={formatUsd(summary.cost_per_1000_calls)}
            current={summary.cost_per_1000_calls}
            previous={previous.cost_per_1000_calls}
            upIsGood={false}
            periodLabel={period}
            hint={`${formatUsd(summary.avg_cost_per_call)} per call`}
          />
          <StatTile
            label="Failed calls"
            value={formatPercent(summary.error_rate)}
            current={summary.error_rate}
            previous={previous.error_rate}
            upIsGood={false}
            periodLabel={period}
            hint={`${formatCount(summary.failed_calls)} of ${formatCount(summary.calls)}`}
          />
        </TileGrid>
        {summary.unidentified_calls > 0 && (
          <Alert severity="warning" sx={{ mt: 1.5 }}>
            <strong>
              {formatCount(summary.unidentified_calls)} {summary.unidentified_calls === 1 ? "call" : "calls"} arrived without a
              user ID.
            </strong>{" "}
            Signing in is required to use the chatbot, so this points to the chat app not sending the user ID{" "}
            <code>X-AWN-User-Id</code>. These calls count toward spending but not toward users or sessions.
          </Alert>
        )}
      </section>

      <section aria-labelledby="users-heading-section">
        <SectionHeading id="users-heading-section">Users and sessions</SectionHeading>
        <ChartRow>
          <ChartCard
            title={`Active users per ${unit}`}
            subtitle="Logged-in users who asked the chatbot at least one question"
            empty={empty}
            table={{
              columns: [
                dateColumn,
                { key: "users", label: "Active users", numeric: true },
                { key: "sessions", label: "Sessions", numeric: true },
                { key: "spu", label: "Sessions per user", numeric: true },
              ],
              rows: series.map((p, i) => ({
                date: categories[i],
                users: formatCount(p.users),
                sessions: formatCount(p.sessions),
                spu: formatDecimal(p.avg_sessions_per_user),
              })),
            }}
          >
            <ColumnChart label={`Active users per ${unit}`} categories={categories} ticks={ticks} series={usersSeries} formatValue={count} />
          </ChartCard>
          <ChartCard
            title={`Successful sessions per ${unit}`}
            subtitle="Login sessions in which every call was answered, by the day the session started"
            empty={series.every((p) => p.sessions === 0)}
            table={{
              columns: [
                dateColumn,
                { key: "rate", label: "Successful", numeric: true },
                { key: "count", label: "Successful / sessions", numeric: true },
              ],
              rows: series.map((p, i) => ({
                date: categories[i],
                rate: formatPercent(p.successful_session_rate),
                count: `${formatCount(p.successful_sessions)} / ${formatCount(p.sessions)}`,
              })),
            }}
          >
            <ColumnChart
              label={`Successful sessions per ${unit}`}
              categories={categories}
              ticks={ticks}
              series={sessionSeries}
              formatValue={formatPercent}
              formatAxis={percentAxis}
            />
          </ChartCard>
        </ChartRow>
      </section>

      <section aria-labelledby="users-cost-heading">
        <SectionHeading id="users-cost-heading">Cost per user</SectionHeading>
        {/* keyed by range so paging restarts at the first page when the range changes */}
        <UserCostTable key={rangeKey} range={rangeKey} token={token} refreshCount={refreshCount} periodLabel={period} />
      </section>

      <section aria-labelledby="quality-heading">
        <SectionHeading id="quality-heading">Retrieval quality</SectionHeading>
        <QualityPanel quality={quality} />
      </section>

      <section aria-labelledby="cost-heading">
        <SectionHeading id="cost-heading">Spending</SectionHeading>
        <ChartRow columns={3}>
          <BudgetCard budget={metrics.budget} />
          <ChartCard
            title={`LLM spending per ${unit}`}
            subtitle="Real spending on model requests. OpenRouter's free models cost $0."
            empty={empty}
            table={{
              columns: [
                dateColumn,
                { key: "cost", label: "LLM spending", numeric: true },
                { key: "per1000", label: "Per 1,000 calls", numeric: true },
              ],
              rows: series.map((p, i) => ({ date: categories[i], cost: formatUsd(p.cost_usd), per1000: formatUsd(p.cost_per_1000_calls) })),
            }}
          >
            <ColumnChart label={`LLM spending per ${unit}`} categories={categories} ticks={ticks} series={costSeries} formatValue={formatUsd} formatAxis={usdAxis} />
          </ChartCard>
          <ChartCard
            title={`Calls per ${unit}`}
            subtitle="One call is one question answered end to end"
            empty={empty}
            table={{
              columns: [
                dateColumn,
                { key: "calls", label: "Calls", numeric: true },
                { key: "models", label: "Model requests", numeric: true },
              ],
              rows: series.map((p, i) => ({
                date: categories[i],
                calls: formatCount(p.calls),
                models: formatCount(p.model_requests),
              })),
            }}
          >
            <ColumnChart label={`Calls per ${unit}`} categories={categories} ticks={ticks} series={callsSeries} formatValue={count} />
          </ChartCard>
        </ChartRow>

        <TableCard
          id="models-heading"
          title="Spending by model"
          subtitle="Each call makes several model requests. Token counts as reported by each model; ~ marks an estimate."
        >
          {unpriced.length > 0 && (
            <Alert severity="warning" sx={{ mb: 1 }}>
              <strong>Spending is understated.</strong> {unpriced.map((m) => m.model).join(", ")}{" "}
              {unpriced.length === 1 ? "has" : "have"} no price per token set in <code>pricing.yaml</code>, so{" "}
              {unpriced.length === 1 ? "its requests are" : "their requests are"} counted as $0. Add the price to{" "}
              <code>code_/backend/analytics/pricing.yaml</code>.
            </Alert>
          )}
          <DataTable
            caption="Spending by model"
            columns={[
              { key: "model", label: "Model" },
              { key: "kind", label: "Type" },
              { key: "calls", label: "Model requests", numeric: true },
              { key: "tokens", label: "Tokens in / out", numeric: true },
              { key: "cost", label: "Spending", numeric: true },
              { key: "source", label: "Cost source" },
              { key: "latency", label: "Median latency", numeric: true },
            ]}
            rows={metrics.by_model.map((m) => ({
              model: m.model,
              kind: m.kind === "chat" ? "Chat" : "Embedding",
              calls: `${formatCount(m.calls)}${m.failed_calls ? ` (${formatCount(m.failed_calls)} failed)` : ""}`,
              tokens: `${m.tokens_estimated ? "~" : ""}${formatCount(m.input_tokens)} / ${formatCount(m.output_tokens)}`,
              cost: m.priced ? formatUsd(m.cost_usd) : "—",
              source: COST_SOURCE_LABELS[m.cost_source] ?? m.cost_source,
              latency: formatMs(m.latency_p50_ms),
            }))}
          />
        </TableCard>
      </section>

      <section aria-labelledby="performance-heading">
        <SectionHeading id="performance-heading">Query performance</SectionHeading>
        <ChartRow columns={3}>
          <ChartCard
            title="Response time"
            subtitle={`End-to-end time to answer a call; the target is under ${target}`}
            legend={latencySeries}
            legendShape="line"
            empty={empty}
            table={{
              columns: [dateColumn, { key: "p50", label: "Median", numeric: true }, { key: "p95", label: "95th percentile", numeric: true }],
              rows: series.map((p, i) => ({ date: categories[i], p50: formatMs(p.latency_p50_ms), p95: formatMs(p.latency_p95_ms) })),
            }}
          >
            <LineChart
              label="Response time"
              categories={categories}
              ticks={ticks}
              series={latencySeries}
              formatValue={formatMs}
              formatAxis={msAxis}
              target={{ value: metrics.target_ms, label: `${target} target` }}
            />
          </ChartCard>
          <ChartCard
            title={`Answered within ${target}`}
            subtitle="Share of answered calls that met the response time target"
            empty={empty}
            table={{
              columns: [dateColumn, { key: "rate", label: `Within ${target}`, numeric: true }],
              rows: series.map((p, i) => ({ date: categories[i], rate: formatPercent(p.within_target_rate) })),
            }}
          >
            <ColumnChart
              label={`Answered within ${target}`}
              categories={categories}
              ticks={ticks}
              series={withinTargetSeries}
              formatValue={formatPercent}
              formatAxis={percentAxis}
            />
          </ChartCard>
          <ChartCard
            title="Failed calls"
            subtitle="Calls that errored, were rate limited, or hit an outage"
            empty={empty}
            table={{
              columns: [dateColumn, { key: "rate", label: "Failed", numeric: true }, { key: "count", label: "Failed / calls", numeric: true }],
              rows: series.map((p, i) => ({
                date: categories[i],
                rate: formatPercent(p.error_rate),
                count: `${formatCount(p.failed_calls)} / ${formatCount(p.calls)}`,
              })),
            }}
          >
            <ColumnChart label="Failed calls" categories={categories} ticks={ticks} series={errorSeries} formatValue={formatPercent} formatAxis={percentAxis} />
          </ChartCard>
        </ChartRow>

        <TableCard id="outcomes-heading" title="Calls by outcome">
          <DataTable
            caption="Calls by outcome"
            columns={[
              { key: "status", label: "Outcome" },
              { key: "requests", label: "Calls", numeric: true },
              { key: "share", label: "Share", numeric: true },
            ]}
            rows={metrics.by_status.map((s) => ({
              status: STATUS_LABELS[s.status] ?? s.status,
              requests: formatCount(s.requests),
              share: formatPercent(summary.calls ? s.requests / summary.calls : null),
            }))}
          />
        </TableCard>
      </section>
    </>
  );
}
