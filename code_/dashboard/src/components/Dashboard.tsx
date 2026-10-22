import {
  formatBucket,
  formatBucketTick,
  formatCount,
  formatDecimal,
  formatMs,
  formatPercent,
  formatUsd,
} from "../format";
import { scaleBasis } from "../projection";
import type { Metrics, RangeKey } from "../types";
import ChartCard from "./ChartCard";
import ColumnChart from "./ColumnChart";
import DataTable from "./DataTable";
import LineChart from "./LineChart";
import ScaleProjection from "./ScaleProjection";
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

type DashboardProps = { metrics: Metrics; range: RangeKey; token: string; refreshCount: number };

export default function Dashboard({ metrics, range: rangeKey, token, refreshCount }: DashboardProps) {
  const { summary, previous, series, months, range } = metrics;
  const period = periodLabels[range.days] ?? `${range.days} days`;
  const empty = summary.requests === 0;

  const categories = series.map((p) => formatBucket(p.bucket, range.bucket));
  const ticks = series.map((p) => formatBucketTick(p.bucket, range.bucket));
  const monthNames = months.map((m) => `${formatBucket(m.bucket, "month")}${m.partial ? " (to date)" : ""}`);
  const monthTicks = months.map((m) => `${formatBucketTick(m.bucket, "month")}${m.partial ? "*" : ""}`);

  const costSeries: Series[] = [{ key: "cost", label: "LLM cost", color: "var(--series-1)", values: series.map((p) => p.cost_usd) }];
  const callSeries: Series[] = [
    { key: "chat", label: "Chat model calls", color: "var(--series-1)", values: series.map((p) => p.chat_calls) },
    { key: "embedding", label: "Embedding calls", color: "var(--series-2)", values: series.map((p) => p.embedding_calls) },
  ];
  const userSeries: Series[] = [{ key: "users", label: "Monthly active users", color: "var(--series-1)", values: months.map((m) => m.users) }];
  const costPerUserSeries: Series[] = [
    { key: "cpu", label: "Cost per user", color: "var(--series-1)", values: months.map((m) => m.avg_cost_per_user) },
  ];
  const latencySeries: Series[] = [
    { key: "p50", label: "Median", endLabel: "p50", color: "var(--series-1)", values: series.map((p) => p.latency_p50_ms) },
    { key: "p95", label: "95th percentile", endLabel: "p95", color: "var(--series-2)", values: series.map((p) => p.latency_p95_ms) },
  ];
  const errorSeries: Series[] = [
    { key: "errors", label: "Failed requests", color: "var(--series-1)", values: series.map((p) => p.error_rate) },
  ];

  const unpriced = metrics.by_model.filter((m) => !m.priced);
  const currentMonth = months.find((m) => m.partial) ?? months[months.length - 1];

  return (
    <>
      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="section-heading">
          Overview
        </h2>
        <div className="overview-grid">
          <StatTile
            hero
            label={`LLM cost, last ${period}`}
            value={formatUsd(summary.cost_usd)}
            current={summary.cost_usd}
            previous={previous.cost_usd}
            periodLabel={period}
            hint={`${formatUsd(summary.avg_cost_per_request)} per question answered`}
          />
          <div className="kpi-grid">
            <StatTile label="LLM calls" value={formatCount(summary.llm_calls)} current={summary.llm_calls} previous={previous.llm_calls} periodLabel={period} hint={`${formatCount(summary.requests)} questions`} />
            <StatTile label="Cost per call" value={formatUsd(summary.avg_cost_per_call)} current={summary.avg_cost_per_call} previous={previous.avg_cost_per_call} upIsGood={false} periodLabel={period} />
            <StatTile label="Active users" value={formatCount(summary.users)} current={summary.users} previous={previous.users} upIsGood periodLabel={period} />
            <StatTile label="Cost per user" value={formatUsd(summary.avg_cost_per_user)} current={summary.avg_cost_per_user} previous={previous.avg_cost_per_user} upIsGood={false} periodLabel={period} />
            <StatTile
              label="Sessions per user"
              value={formatDecimal(summary.avg_sessions_per_user)}
              current={summary.avg_sessions_per_user}
              previous={previous.avg_sessions_per_user}
              upIsGood
              periodLabel={period}
              hint={`${formatDecimal(summary.avg_requests_per_session)} questions per session`}
            />
            <StatTile label="Response time (p95)" value={formatMs(summary.latency_p95_ms)} current={summary.latency_p95_ms} previous={previous.latency_p95_ms} upIsGood={false} periodLabel={period} hint={`Median ${formatMs(summary.latency_p50_ms)}`} />
            <StatTile label="Failed requests" value={formatPercent(summary.error_rate)} current={summary.error_rate} previous={previous.error_rate} upIsGood={false} periodLabel={period} hint={`${formatCount(summary.failed_requests)} of ${formatCount(summary.requests)}`} />
          </div>
        </div>
        {summary.unidentified_requests > 0 && (
          <p className="note">
            {summary.unidentified_requests === 1
              ? "1 question arrived without a user id. It counts"
              : `${formatCount(summary.unidentified_requests)} questions arrived without a user id. They count`}{" "}
            toward cost and calls but not toward users, sessions, or cost per user.
          </p>
        )}
      </section>

      <section aria-labelledby="users-cost-heading">
        <h2 id="users-cost-heading" className="section-heading">
          Cost per user
        </h2>
        {/* keyed by range so paging restarts at the first page when the range changes */}
        <UserCostTable key={rangeKey} range={rangeKey} token={token} refreshCount={refreshCount} periodLabel={period} />
      </section>

      <section aria-labelledby="cost-heading">
        <h2 id="cost-heading" className="section-heading">
          Cost and calls
        </h2>
        <div className="chart-grid">
          <ChartCard
            title={`LLM cost per ${range.bucket}`}
            subtitle="Tokens used × each model's price per token. Free models cost $0. Details below."
            empty={empty}
            table={{
              columns: [{ key: "date", label: "Date" }, { key: "cost", label: "LLM cost", numeric: true }],
              rows: series.map((p, i) => ({ date: categories[i], cost: formatUsd(p.cost_usd) })),
            }}
          >
            <ColumnChart label={`LLM cost per ${range.bucket}`} categories={categories} ticks={ticks} series={costSeries} formatValue={formatUsd} formatAxis={usdAxis} />
          </ChartCard>
          <ChartCard
            title={`LLM calls per ${range.bucket}`}
            subtitle="Each question makes one chat call and one embedding call per data source"
            legend={callSeries}
            empty={empty}
            table={{
              columns: [
                { key: "date", label: "Date" },
                { key: "chat", label: "Chat calls", numeric: true },
                { key: "embedding", label: "Embedding calls", numeric: true },
                { key: "total", label: "Total", numeric: true },
              ],
              rows: series.map((p, i) => ({
                date: categories[i],
                chat: formatCount(p.chat_calls),
                embedding: formatCount(p.embedding_calls),
                total: formatCount(p.llm_calls),
              })),
            }}
          >
            <ColumnChart label={`LLM calls per ${range.bucket}`} categories={categories} ticks={ticks} series={callSeries} formatValue={count} />
          </ChartCard>
        </div>

        <section className="card" aria-labelledby="models-heading">
          <header className="card-header">
            <div>
              <h3 id="models-heading">Cost by model</h3>
              <p className="card-subtitle">
                Token counts as reported by each model. ~ marks an estimate where no count was reported.
              </p>
            </div>
          </header>
          {unpriced.length > 0 && (
            <p className="note note-warning" role="note">
              <strong>Cost is understated.</strong> {unpriced.map((m) => m.model).join(", ")}{" "}
              {unpriced.length === 1 ? "has" : "have"} no price per token set in <code>pricing.yaml</code>, so{" "}
              {unpriced.length === 1 ? "its calls are" : "their calls are"} counted as $0. Add the price to{" "}
              <code>code_/backend/analytics/pricing.yaml</code>.
            </p>
          )}
          <DataTable
            caption="Cost by model"
            columns={[
              { key: "model", label: "Model" },
              { key: "kind", label: "Type" },
              { key: "calls", label: "Calls", numeric: true },
              { key: "tokens", label: "Tokens in / out", numeric: true },
              { key: "cost", label: "Cost", numeric: true },
              { key: "source", label: "Cost source" },
              { key: "per", label: "Cost per call", numeric: true },
              { key: "latency", label: "Median latency", numeric: true },
            ]}
            rows={metrics.by_model.map((m) => ({
              model: m.model,
              kind: m.kind === "chat" ? "Chat" : "Embedding",
              calls: `${formatCount(m.calls)}${m.failed_calls ? ` (${formatCount(m.failed_calls)} failed)` : ""}`,
              tokens: `${m.tokens_estimated ? "~" : ""}${formatCount(m.input_tokens)} / ${formatCount(m.output_tokens)}`,
              cost: m.priced ? formatUsd(m.cost_usd) : "—",
              source: COST_SOURCE_LABELS[m.cost_source] ?? m.cost_source,
              per: m.priced ? formatUsd(m.avg_cost_per_call) : "—",
              latency: formatMs(m.latency_p50_ms),
            }))}
          />
        </section>
      </section>

      <section aria-labelledby="scale-heading">
        <h2 id="scale-heading" className="section-heading">
          Users and scale
        </h2>
        <div className="chart-grid chart-grid-3">
          <ChartCard
            title="Monthly active users"
            subtitle={months.some((m) => m.partial) ? "* current month to date" : "Distinct users per calendar month"}
            empty={months.every((m) => m.users === 0)}
            table={{
              columns: [
                { key: "month", label: "Month" },
                { key: "users", label: "Users", numeric: true },
                { key: "sessions", label: "Sessions per user", numeric: true },
                { key: "calls", label: "LLM calls", numeric: true },
                { key: "cost", label: "LLM cost", numeric: true },
              ],
              rows: months.map((m, i) => ({
                month: monthNames[i],
                users: formatCount(m.users),
                sessions: formatDecimal(m.avg_sessions_per_user),
                calls: formatCount(m.llm_calls),
                cost: formatUsd(m.cost_usd),
              })),
            }}
          >
            <ColumnChart label="Monthly active users" categories={monthNames} ticks={monthTicks} series={userSeries} formatValue={count} />
          </ChartCard>
          <ChartCard
            title="Cost per user by month"
            subtitle="LLM cost of identified users ÷ monthly active users"
            empty={months.every((m) => m.avg_cost_per_user == null)}
            table={{
              columns: [{ key: "month", label: "Month" }, { key: "cpu", label: "Cost per user", numeric: true }],
              rows: months.map((m, i) => ({ month: monthNames[i], cpu: formatUsd(m.avg_cost_per_user) })),
            }}
          >
            <ColumnChart label="Cost per user by month" categories={monthNames} ticks={monthTicks} series={costPerUserSeries} formatValue={formatUsd} formatAxis={usdAxis} />
          </ChartCard>
          <ScaleProjection basis={scaleBasis(months)} currentUsers={currentMonth?.users ?? 0} />
        </div>
      </section>

      <section aria-labelledby="performance-heading">
        <h2 id="performance-heading" className="section-heading">
          Query performance
        </h2>
        <div className="chart-grid">
          <ChartCard
            title="Response time"
            subtitle="Time to answer a question, answered requests only"
            legend={latencySeries}
            legendShape="line"
            empty={empty}
            table={{
              columns: [
                { key: "date", label: "Date" },
                { key: "p50", label: "Median", numeric: true },
                { key: "p95", label: "95th percentile", numeric: true },
              ],
              rows: series.map((p, i) => ({ date: categories[i], p50: formatMs(p.latency_p50_ms), p95: formatMs(p.latency_p95_ms) })),
            }}
          >
            <LineChart label="Response time" categories={categories} ticks={ticks} series={latencySeries} formatValue={formatMs} formatAxis={msAxis} />
          </ChartCard>
          <ChartCard
            title="Failed requests"
            subtitle="Share of questions that errored, were rate limited, or hit an outage"
            empty={empty}
            table={{
              columns: [
                { key: "date", label: "Date" },
                { key: "rate", label: "Failed", numeric: true },
                { key: "count", label: "Failed / total", numeric: true },
              ],
              rows: series.map((p, i) => ({
                date: categories[i],
                rate: formatPercent(p.error_rate),
                count: `${formatCount(p.failed_requests)} / ${formatCount(p.requests)}`,
              })),
            }}
          >
            <ColumnChart label="Failed requests" categories={categories} ticks={ticks} series={errorSeries} formatValue={formatPercent} formatAxis={percentAxis} />
          </ChartCard>
        </div>

        <section className="card" aria-labelledby="outcomes-heading">
          <header className="card-header">
            <h3 id="outcomes-heading">Requests by outcome</h3>
          </header>
          <DataTable
            caption="Requests by outcome"
            columns={[
              { key: "status", label: "Outcome" },
              { key: "requests", label: "Requests", numeric: true },
              { key: "share", label: "Share", numeric: true },
            ]}
            rows={metrics.by_status.map((s) => ({
              status: STATUS_LABELS[s.status] ?? s.status,
              requests: formatCount(s.requests),
              share: formatPercent(summary.requests ? s.requests / summary.requests : null),
            }))}
          />
        </section>
      </section>
    </>
  );
}
