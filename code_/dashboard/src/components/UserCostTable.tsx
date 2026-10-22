import { useEffect, useState } from "react";
import { downloadUsersCsv, fetchUsers } from "../api";
import { formatCount, formatPercent, formatUsd } from "../format";
import type { RangeKey, UserRow, UsersPage } from "../types";
import DataTable from "./DataTable";

const PAGE_SIZE = 25;

type UserCostTableProps = {
  range: RangeKey;
  token: string;
  /** Changes when the page's Refresh button is pressed. */
  refreshCount: number;
  periodLabel: string;
};

const lastActive = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function row(user: UserRow) {
  return {
    user: user.user_id ? (
      <span className="user-id" title={user.user_id}>
        {user.user_id}
      </span>
    ) : (
      <span className="muted">Unidentified (no user id)</span>
    ),
    questions: formatCount(user.requests),
    sessions: user.user_id ? formatCount(user.sessions) : "—",
    calls: formatCount(user.llm_calls),
    tokens: `${formatCount(user.input_tokens)} / ${formatCount(user.output_tokens)}`,
    cost: formatUsd(user.cost_usd),
    share: formatPercent(user.cost_share),
    perQuestion: formatUsd(user.avg_cost_per_request),
    lastActive: user.last_seen ? lastActive.format(new Date(user.last_seen)) : "—",
  };
}

/** Every user's LLM cost for the selected range, most expensive first, a page at a time. */
export default function UserCostTable({ range, token, refreshCount, periodLabel }: UserCostTableProps) {
  const [offset, setOffset] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; page: UsersPage } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [downloading, setDownloading] = useState(false);

  const requestKey = `${range}|${offset}|${refreshCount}`;
  const page = loaded?.page ?? null;
  const loading = loaded?.key !== requestKey && failure?.key !== requestKey;
  const error = failure?.key === requestKey ? failure.message : null;

  useEffect(() => {
    const controller = new AbortController();
    fetchUsers(range, token, offset, PAGE_SIZE, controller.signal).then(
      (data) => setLoaded({ key: requestKey, page: data }),
      (err: unknown) => {
        if (!controller.signal.aborted) {
          setFailure({ key: requestKey, message: err instanceof Error ? err.message : "Per user costs could not be loaded." });
        }
      },
    );
    return () => controller.abort();
  }, [range, token, offset, requestKey]);

  async function download() {
    setDownloading(true);
    try {
      await downloadUsersCsv(range, token);
    } catch (err) {
      setFailure({ key: requestKey, message: err instanceof Error ? err.message : "The CSV could not be downloaded." });
    } finally {
      setDownloading(false);
    }
  }

  const total = page?.total_users ?? 0;
  const rows = (page?.users ?? []).map(row);
  const lastPage = page !== null && offset + PAGE_SIZE >= total;
  if (page?.unidentified && lastPage) rows.push(row(page.unidentified));

  return (
    <section className="card" aria-labelledby="users-heading">
      <header className="card-header">
        <div>
          <h3 id="users-heading">Users by LLM cost</h3>
          <p className="card-subtitle">
            {page && total > 0
              ? `${formatCount(total)} users in the last ${periodLabel}` +
                (page.top_decile_cost_share != null
                  ? ` · the top 10% of users account for ${formatPercent(page.top_decile_cost_share)} of LLM cost`
                  : "")
              : "Each user's questions, LLM calls, and cost, most expensive first"}
          </p>
        </div>
        <button type="button" className="ghost-button" onClick={() => void download()} disabled={downloading || total === 0}>
          {downloading ? "Preparing…" : "Download CSV"}
        </button>
      </header>

      {error && (
        <p className="note note-warning" role="alert">
          {error}
        </p>
      )}

      {page && total === 0 && page.unidentified && (
        <p className="note note-warning" role="note">
          <strong>No user ids recorded.</strong> All {formatCount(page.unidentified.requests)} questions in this range arrived
          without a user id, so cost cannot be split by user. The chat app needs to send an <code>X-AWN-User-Id</code> with
          each question.
        </p>
      )}

      <div className={loading && page ? "is-refreshing" : undefined} aria-busy={loading}>
        {page ? (
          <DataTable
            caption="LLM cost by user"
            empty="No questions recorded in this range yet."
            columns={[
              { key: "user", label: "User" },
              { key: "questions", label: "Questions", numeric: true },
              { key: "sessions", label: "Sessions", numeric: true },
              { key: "calls", label: "LLM calls", numeric: true },
              { key: "tokens", label: "Tokens in / out", numeric: true },
              { key: "cost", label: "LLM cost", numeric: true },
              { key: "share", label: "Share of cost", numeric: true },
              { key: "perQuestion", label: "Cost per question", numeric: true },
              { key: "lastActive", label: "Last active", numeric: true },
            ]}
            rows={rows}
          />
        ) : (
          !error && <p className="muted loading-note">Loading users…</p>
        )}
      </div>

      {total > PAGE_SIZE && (
        <nav className="pager" aria-label="Users pages">
          <button type="button" className="ghost-button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>
          <span className="muted">
            {formatCount(offset + 1)}–{formatCount(Math.min(offset + PAGE_SIZE, total))} of {formatCount(total)} users
          </span>
          <button type="button" className="ghost-button" disabled={lastPage || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
