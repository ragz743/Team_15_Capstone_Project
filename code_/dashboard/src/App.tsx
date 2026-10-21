import { useEffect, useRef, useState } from "react";
import { ApiError, fetchMetrics } from "./api";
import Dashboard from "./components/Dashboard";
import TokenGate from "./components/TokenGate";
import WsuLogo from "./components/WsuLogo";
import type { Metrics, RangeKey } from "./types";

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "12m", label: "12 months" },
];

const TOKEN_KEY = "awn-admin-token";
const RANGE_KEY = "awn-admin-range";

// storage can throw (private mode, blocked site data); the dashboard works without it
function readStorage(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(storage: () => Storage, key: string, value: string | null) {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // ignore
  }
}
const session = () => window.sessionStorage;
const local = () => window.localStorage;

function initialRange(): RangeKey {
  const saved = readStorage(local, RANGE_KEY);
  return RANGES.some((r) => r.key === saved) ? (saved as RangeKey) : "30d";
}

const updatedFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

export default function App() {
  // the token lives in sessionStorage so it is forgotten when the tab closes
  const [token, setToken] = useState<string | null>(() => readStorage(session, TOKEN_KEY));
  const [range, setRange] = useState<RangeKey>(initialRange);
  const [refreshCount, setRefreshCount] = useState(0);
  // results are tagged with the request they answer, so "loading" is simply "no result for this key yet"
  const [loaded, setLoaded] = useState<{ key: string; metrics: Metrics; at: Date } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const hasMetrics = useRef(false);

  const requestKey = `${token}|${range}|${refreshCount}`;
  const metrics = loaded?.metrics ?? null;
  const loading = token !== null && loaded?.key !== requestKey && failure?.key !== requestKey;
  const error = failure?.key === requestKey ? failure.message : null;

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    fetchMetrics(range, token, controller.signal).then(
      (data) => {
        hasMetrics.current = true;
        setLoaded({ key: requestKey, metrics: data, at: new Date() });
      },
      (err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && (err.status === 401 || (err.status === 503 && !hasMetrics.current))) {
          // wrong token, or the dashboard is not configured on the server: back to sign in
          writeStorage(session, TOKEN_KEY, null);
          setToken(null);
          setAuthError(err.status === 401 ? "That token was not accepted." : err.message);
        } else {
          setFailure({ key: requestKey, message: err instanceof Error ? err.message : "Metrics could not be loaded." });
        }
      },
    );
    return () => controller.abort();
  }, [token, range, requestKey]);

  function signIn(newToken: string) {
    writeStorage(session, TOKEN_KEY, newToken);
    setAuthError(null);
    setToken(newToken);
  }

  function signOut() {
    writeStorage(session, TOKEN_KEY, null);
    hasMetrics.current = false;
    setLoaded(null);
    setToken(null);
  }

  function selectRange(next: RangeKey) {
    writeStorage(local, RANGE_KEY, next);
    setRange(next);
  }

  if (!token) {
    return <TokenGate error={authError} checking={false} onSubmit={signIn} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <WsuLogo />
          </span>
          <div>
            <div className="brand-name">AgWeatherNet</div>
            <div className="brand-sub">Admin dashboard</div>
          </div>
        </div>
        <button type="button" className="ghost-button" onClick={signOut}>
          Sign out
        </button>
      </header>

      <main className="content">
        <div className="page-title">
          <h1>LLM usage dashboard</h1>
          <p className="card-subtitle">Cost, users, and performance of the AgWeatherNet weather assistant.</p>
        </div>

        <div className="filter-row">
          <div className="segmented" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => selectRange(r.key)}>
                {r.label}
              </button>
            ))}
          </div>
          <button type="button" className="ghost-button" onClick={() => setRefreshCount((n) => n + 1)} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          {loaded && <span className="muted">Updated {updatedFormatter.format(loaded.at)}</span>}
          {metrics?.includes_demo_data && (
            <span className="badge" title="Rows created by scripts/seed_dashboard_demo.py">
              Includes demo data
            </span>
          )}
        </div>

        {error && (
          <p className="note note-warning" role="alert">
            {error} {metrics && "Showing the last loaded data."}
          </p>
        )}

        {metrics ? (
          <div className={loading ? "dashboard is-refreshing" : "dashboard"} aria-busy={loading}>
            <Dashboard metrics={metrics} />
          </div>
        ) : (
          !error && <p className="muted loading-note">Loading metrics…</p>
        )}

        <footer className="definitions">
          <h2>How these numbers are measured</h2>
          <dl>
            <dt>LLM calls</dt>
            <dd>Every request to a chat or embedding model made while answering a question.</dd>
            <dt>LLM cost</dt>
            <dd>
              Token usage × the prices in <code>pricing.yaml</code>. Free tier and local models cost $0; models missing from
              the file are flagged as unpriced.
            </dd>
            <dt>Users and sessions</dt>
            <dd>
              Anonymous user and conversation ids sent by the chat app. No question text or personal information is stored.
            </dd>
            <dt>Response time</dt>
            <dd>Time from receiving a question to returning the answer, measured on the API server.</dd>
          </dl>
          {metrics && <p className="muted">Dates are in {metrics.range.timezone.replace("_", " ")} time.</p>}
          <div className="university">
            <span className="university-mark">
              <WsuLogo />
            </span>
            <div>
              <strong>Washington State University</strong>
              <span>AgWeatherNet</span>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
