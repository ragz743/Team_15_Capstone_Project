import DownloadIcon from "@mui/icons-material/Download";
import LogoutIcon from "@mui/icons-material/Logout";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, downloadMetricsCsv, fetchMetrics } from "./api";
import Dashboard from "./components/Dashboard";
import TokenGate from "./components/TokenGate";
import WsuLogo from "./components/WsuLogo";
import type { Bucket, Metrics, RangeKey } from "./types";

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "12m", label: "12 months" },
];

const BUCKETS: { key: Bucket; label: string }[] = [
  { key: "day", label: "Daily" },
  { key: "week", label: "Weekly" },
  { key: "month", label: "Monthly" },
];

const TOKEN_KEY = "awn-admin-token";
const RANGE_KEY = "awn-admin-range";
const BUCKET_KEY = "awn-admin-bucket";
// the client asked for hourly updates; the page reloads its data on this interval while open
const AUTO_REFRESH_MS = 60 * 60 * 1000;

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

function initialBucket(): Bucket {
  const saved = readStorage(local, BUCKET_KEY);
  return BUCKETS.some((b) => b.key === saved) ? (saved as Bucket) : "day";
}

/** Plain language definitions shown at the bottom of the page. */
function definitions(metrics: Metrics | null): [string, ReactNode][] {
  return [
    [
      "Active users",
      "Signed-in users identified by the host website who asked the chatbot at least one question. Calls without a user ID are flagged as unidentified: they count toward spending but not users.",
    ],
    ["Sessions", "One login session identified by the host website. A session is successful when every call in it was answered."],
    ["Calls", "One attempt to answer a question. A call can make several model requests. Reopening a saved answer adds no usage."],
    [
      "Retrieval quality",
      "The share of a fixed set of sample questions where the chatbot found the right weather data. Once a day each question is asked at its station through the chatbot's workflow, and it passes when the chatbot queried the expected kind of data (current conditions, past days, or forecast) and got records back. A model error during the check counts as a miss.",
    ],
    [
      "Tokens",
      "The units of text a model reads and writes. Usage includes each model request in the workflow. Provider-reported counts are used when available; estimated counts are labelled.",
    ],
    [
      "LLM spending",
      <>
        Real spending on model requests only, not hosting: tokens used × each model&rsquo;s price per token from{" "}
        <code>code_/backend/analytics/pricing.yaml</code>, or the exact amount when the provider reports one. OpenRouter&rsquo;s
        free models cost $0. Demo data never counts toward the monthly budget.
      </>,
    ],
    [
      "Response time",
      `Time from receiving a question to returning the answer, measured on the API server. The target is under ${
        metrics ? metrics.target_ms / 1000 : 5
      } seconds.`,
    ],
  ];
}

const updatedFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

export default function App() {
  // the token lives in sessionStorage so it is forgotten when the tab closes
  const [token, setToken] = useState<string | null>(() => readStorage(session, TOKEN_KEY));
  const [range, setRange] = useState<RangeKey>(initialRange);
  const [bucket, setBucket] = useState<Bucket>(initialBucket);
  const [refreshCount, setRefreshCount] = useState(0);
  const [exporting, setExporting] = useState(false);
  // results are tagged with the request they answer, so "loading" is simply "no result for this key yet"
  const [loaded, setLoaded] = useState<{ key: string; metrics: Metrics; at: Date } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const hasMetrics = useRef(false);

  const requestKey = `${token}|${range}|${bucket}|${refreshCount}`;
  const metrics = loaded?.metrics ?? null;
  const loading = token !== null && loaded?.key !== requestKey && failure?.key !== requestKey;
  const error = failure?.key === requestKey ? failure.message : null;

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    fetchMetrics(range, bucket, token, controller.signal).then(
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
  }, [token, range, bucket, requestKey]);

  // reload the data every hour while the page is open
  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => setRefreshCount((n) => n + 1), AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [token]);

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

  function selectBucket(next: Bucket) {
    writeStorage(local, BUCKET_KEY, next);
    setBucket(next);
  }

  async function exportCsv() {
    if (!token) return;
    setExporting(true);
    try {
      await downloadMetricsCsv(range, bucket, token);
    } catch (err) {
      setFailure({ key: requestKey, message: err instanceof Error ? err.message : "The CSV could not be downloaded." });
    } finally {
      setExporting(false);
    }
  }

  if (!token) {
    return <TokenGate error={authError} checking={false} onSubmit={signIn} />;
  }

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar sx={{ gap: 2, maxWidth: 1280, width: "100%", mx: "auto", px: { xs: 2, sm: 3 } }}>
          <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", flexGrow: 1 }}>
            <Box className="brand-mark">
              <WsuLogo />
            </Box>
            <div>
              <Typography sx={{ fontSize: 16, fontWeight: 650, letterSpacing: "-0.5px", lineHeight: 1.4 }}>AgWeatherNet</Typography>
              <Typography variant="caption" color="text.secondary">
                Admin dashboard
              </Typography>
            </div>
          </Stack>
          <Button variant="outlined" color="inherit" startIcon={<LogoutIcon />} onClick={signOut}>
            Sign out
          </Button>
        </Toolbar>
      </AppBar>

      <Box component="main" sx={{ maxWidth: 1280, mx: "auto", px: { xs: 2, sm: 3 }, pt: 3, pb: 6 }}>
        <Typography variant="h1">LLM usage dashboard</Typography>
        <Typography variant="body2" color="text.secondary">
          Users, retrieval quality, spending, and performance of the AgWeatherNet weather assistant.
        </Typography>

        <Stack
          direction="row"
          spacing={1.5}
          useFlexGap
          className="filter-row"
          sx={{
            flexWrap: "wrap",
            alignItems: "center",
            // pinned while scrolling on wide screens; on phones the wrapped controls would cover too much
            position: { xs: "static", md: "sticky" },
            top: 0,
            zIndex: 5,
            py: 1.25,
            mt: 1,
            bgcolor: "background.default",
          }}
        >
          <ToggleButtonGroup
            size="small"
            exclusive
            value={range}
            onChange={(_, next: RangeKey | null) => next && selectRange(next)}
            aria-label="Date range"
            sx={{ bgcolor: "background.paper" }}
          >
            {RANGES.map((r) => (
              <ToggleButton key={r.key} value={r.key}>
                {r.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={bucket}
            onChange={(_, next: Bucket | null) => next && selectBucket(next)}
            aria-label="Group charts by"
            sx={{ bgcolor: "background.paper" }}
          >
            {BUCKETS.map((b) => (
              <ToggleButton key={b.key} value={b.key}>
                {b.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Button variant="outlined" color="inherit" startIcon={<RefreshIcon />} onClick={() => setRefreshCount((n) => n + 1)} disabled={loading} sx={{ bgcolor: "background.paper" }}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
          <Button variant="outlined" color="inherit" startIcon={<DownloadIcon />} onClick={() => void exportCsv()} disabled={exporting || !metrics} sx={{ bgcolor: "background.paper" }}>
            {exporting ? "Preparing…" : "Export CSV"}
          </Button>
          {loaded && (
            <Typography variant="caption" color="text.secondary" title="The page refreshes its data every hour">
              Updated {updatedFormatter.format(loaded.at)}
            </Typography>
          )}
          {metrics?.includes_demo_data && (
            <Chip size="small" color="warning" variant="outlined" label="Includes demo data" title="Rows created by scripts/seed_dashboard_demo.py" />
          )}
        </Stack>

        {error && (
          <Alert severity="warning" sx={{ my: 1.5 }}>
            {error} {metrics && "Showing the last loaded data."}
          </Alert>
        )}

        {metrics ? (
          <Box sx={{ opacity: loading ? 0.55 : 1, transition: "opacity 160ms ease" }} aria-busy={loading}>
            <Dashboard metrics={metrics} range={range} token={token} refreshCount={refreshCount} />
          </Box>
        ) : (
          !error && (
            <Box sx={{ py: 8, display: "grid", placeItems: "center", gap: 1.5 }}>
              <CircularProgress size={28} />
              <Typography variant="body2" color="text.secondary">
                Loading metrics…
              </Typography>
            </Box>
          )
        )}

        <Box component="footer" sx={{ mt: 5, pt: 2, borderTop: 1, borderColor: "divider" }}>
          <Typography variant="h3" component="h2" sx={{ mb: 1 }}>
            How these numbers are measured
          </Typography>
          <Box component="dl" className="definitions-list" sx={{ m: 0 }}>
            {definitions(metrics).map(([term, description]) => (
              <Grid container key={term} spacing={{ xs: 0, sm: 2 }} sx={{ mb: 0.75 }}>
                <Grid size={{ xs: 12, sm: 2 }} component="dt">
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {term}
                  </Typography>
                </Grid>
                <Grid size={{ xs: 12, sm: 10 }} component="dd" sx={{ m: 0 }}>
                  <Typography variant="body2" color="text.secondary">
                    {description}
                  </Typography>
                </Grid>
              </Grid>
            ))}
          </Box>
          {metrics && (
            <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
              Dates are in {metrics.range.timezone.replace("_", " ")} time.
            </Typography>
          )}
          <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", mt: 2.5 }}>
            <Box className="university-mark">
              <WsuLogo />
            </Box>
            <div>
              <Typography sx={{ fontSize: 10, fontWeight: 600 }}>Washington State University</Typography>
              <Typography sx={{ fontSize: 10 }} color="text.secondary">
                AgWeatherNet
              </Typography>
            </div>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}
