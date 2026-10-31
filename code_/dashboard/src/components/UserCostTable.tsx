import DownloadIcon from "@mui/icons-material/Download";
import SearchIcon from "@mui/icons-material/Search";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  InputAdornment,
  Stack,
  TablePagination,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useId, useState } from "react";
import { downloadUsersCsv, fetchUsers } from "../api";
import { formatCount, formatPercent, formatUsd } from "../format";
import type { RangeKey, UserQuery, UserRow, UserSortField, UsersPage } from "../types";
import DataTable, { type Column, type SortState } from "./DataTable";

const PAGE_SIZE = 25;
const SEARCH_DELAY_MS = 300; // wait for a pause in typing before asking the server

type UserCostTableProps = {
  range: RangeKey;
  token: string;
  /** Changes when the page's Refresh button is pressed. */
  refreshCount: number;
  periodLabel: string;
};

/** Table columns and the server field each one sorts by. Share of cost sorts the same way as cost. */
const COLUMNS: (Column & { sortField: UserSortField })[] = [
  { key: "user", label: "User", sortable: true, sortField: "user_id" },
  { key: "calls", label: "Calls", numeric: true, sortable: true, sortField: "requests" },
  { key: "sessions", label: "Sessions", numeric: true, sortable: true, sortField: "sessions" },
  { key: "tokens", label: "Tokens in / out", numeric: true, sortable: true, sortField: "total_tokens" },
  { key: "cost", label: "LLM cost", numeric: true, sortable: true, sortField: "cost_usd" },
  { key: "share", label: "Share of cost", numeric: true, sortable: true, sortField: "cost_usd" },
  { key: "perCall", label: "Cost per call", numeric: true, sortable: true, sortField: "avg_cost_per_request" },
  { key: "lastActive", label: "Last active", numeric: true, sortable: true, sortField: "last_seen" },
];

// with no column chosen, users are listed most expensive first and no header is marked as sorted
const DEFAULT_ORDER = { sort: "cost_usd", order: "desc" } as const;

const lastActive = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function row(user: UserRow) {
  return {
    user: user.user_id ? (
      <span className="user-id" title={user.user_id}>
        {user.user_id}
      </span>
    ) : (
      <span className="muted">Unidentified (missing user ID)</span>
    ),
    calls: formatCount(user.requests),
    sessions: user.user_id ? formatCount(user.sessions) : "—",
    tokens: `${formatCount(user.input_tokens)} / ${formatCount(user.output_tokens)}`,
    cost: formatUsd(user.cost_usd),
    share: formatPercent(user.cost_share),
    perCall: formatUsd(user.avg_cost_per_request),
    lastActive: user.last_seen ? lastActive.format(new Date(user.last_seen)) : "—",
  };
}

/** Every user's LLM cost for the selected range: searchable, sortable by any column, a page at a time. */
export default function UserCostTable({ range, token, refreshCount, periodLabel }: UserCostTableProps) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<SortState | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState(""); // the search actually sent, updated after typing pauses
  const [loaded, setLoaded] = useState<{ key: string; page: UsersPage } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [downloading, setDownloading] = useState(false);
  const searchId = useId();

  const sortField = (sort && COLUMNS.find((c) => c.key === sort.key)?.sortField) || DEFAULT_ORDER.sort;
  const sortOrder = sort?.direction ?? DEFAULT_ORDER.order;
  const query: UserQuery = { search, sort: sortField, order: sortOrder };
  const requestKey = `${range}|${offset}|${refreshCount}|${search}|${sortField}|${sortOrder}`;
  const page = loaded?.page ?? null;
  const loading = loaded?.key !== requestKey && failure?.key !== requestKey;
  const error = failure?.key === requestKey ? failure.message : null;

  // apply the typed search after a short pause, starting again from the first page
  useEffect(() => {
    if (searchInput.trim() === search) return;
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    const controller = new AbortController();
    fetchUsers(range, token, { search, sort: sortField, order: sortOrder }, offset, PAGE_SIZE, controller.signal).then(
      (data) => setLoaded({ key: requestKey, page: data }),
      (err: unknown) => {
        if (!controller.signal.aborted) {
          setFailure({ key: requestKey, message: err instanceof Error ? err.message : "Per user costs could not be loaded." });
        }
      },
    );
    return () => controller.abort();
  }, [range, token, offset, search, sortField, sortOrder, requestKey]);

  /** Each click on a header cycles: ascending → descending → back to the default order. */
  function changeSort(key: string) {
    setSort((current) => {
      if (current?.key !== key) return { key, direction: "asc" };
      return current.direction === "asc" ? { key, direction: "desc" } : null;
    });
    setOffset(0);
  }

  async function download() {
    setDownloading(true);
    try {
      await downloadUsersCsv(range, token, query);
    } catch (err) {
      setFailure({ key: requestKey, message: err instanceof Error ? err.message : "The CSV could not be downloaded." });
    } finally {
      setDownloading(false);
    }
  }

  const total = page?.total_users ?? 0;
  const matched = page?.matched_users ?? 0;
  const searching = search !== "";
  const rows = (page?.users ?? []).map(row);
  const lastPage = page !== null && offset + PAGE_SIZE >= matched;
  // unidentified calls have no user id to search for, so their row only appears in the unfiltered list
  if (page?.unidentified && lastPage && !searching) rows.push(row(page.unidentified));

  let subtitle = "Each logged-in user's calls, sessions, and spending";
  if (page && searching) {
    subtitle = `${formatCount(matched)} of ${formatCount(total)} users match “${search}”`;
  } else if (page && total > 0) {
    subtitle =
      `${formatCount(total)} users in the last ${periodLabel}` +
      (page.top_decile_cost_share != null
        ? ` · the top 10% of users account for ${formatPercent(page.top_decile_cost_share)} of LLM cost`
        : "");
  }

  return (
    <Card component="section" aria-labelledby="users-heading">
      <CardContent>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={{ xs: 1, sm: 2 }}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", sm: "flex-start" }, mb: 1.5 }}
        >
          <div>
            <Typography id="users-heading" variant="h3">
              Users by LLM cost
            </Typography>
            <Typography className="card-subtitle" variant="body2" color="text.secondary" aria-live="polite">
              {subtitle}
            </Typography>
          </div>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={() => void download()}
            disabled={downloading || matched === 0}
            sx={{ flexShrink: 0 }}
          >
            {downloading ? "Preparing…" : searching ? "Download matches (CSV)" : "Download CSV"}
          </Button>
        </Stack>

        <TextField
          id={searchId}
          type="search"
          size="small"
          placeholder="Search by user ID"
          autoComplete="off"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          sx={{ width: { xs: "100%", sm: 320 }, mb: 1 }}
          slotProps={{
            htmlInput: { maxLength: 64, spellCheck: false, "aria-label": "Search users" },
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />

        {error && (
          <Alert severity="warning" sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {page && total === 0 && page.unidentified && (
          <Alert severity="warning" sx={{ mb: 1 }}>
            <strong>No user IDs recorded.</strong> All {formatCount(page.unidentified.requests)} calls in this range arrived
            without a user ID, so spending cannot be split by user. The chat app needs to send the signed-in user&rsquo;s ID{" "}
            <code>X-AWN-User-Id</code> and login session ID <code>X-AWN-Session-Id</code> with each call.
          </Alert>
        )}

        <Box sx={{ opacity: loading && page ? 0.55 : 1, transition: "opacity 160ms ease" }} aria-busy={loading}>
          {page ? (
            <DataTable
              caption="LLM cost by user"
              empty={searching ? `No users match “${search}”.` : "No calls recorded in this range yet."}
              columns={COLUMNS}
              rows={rows}
              sort={sort ?? undefined}
              onSort={changeSort}
            />
          ) : (
            !error && (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
                Loading users…
              </Typography>
            )
          )}
        </Box>

        {matched > PAGE_SIZE && (
          <TablePagination
            component="div"
            count={matched}
            page={Math.floor(offset / PAGE_SIZE)}
            rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]}
            onPageChange={(_, next) => setOffset(next * PAGE_SIZE)}
            labelDisplayedRows={({ from, to, count }) => `${formatCount(from)}–${formatCount(to)} of ${formatCount(count)} users`}
            disabled={loading}
          />
        )}
      </CardContent>
    </Card>
  );
}
