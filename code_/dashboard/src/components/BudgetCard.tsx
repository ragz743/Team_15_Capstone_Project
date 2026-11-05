import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { Alert, Card, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import { formatPercent, formatUsd, parseBucket } from "../format";
import type { Budget } from "../types";

const monthName = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" });
const sentAt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

// severity carries the meter color, always paired with an icon and a text label
const LEVELS = {
  ok: { label: "Within budget", color: "info", icon: <CheckCircleIcon /> },
  near: { label: "Approaching budget", color: "warning", icon: <WarningAmberIcon /> },
  over: { label: "Over budget", color: "error", icon: <WarningAmberIcon /> },
} as const;

/** This month's real LLM spending against the monthly budget, and the state of the alert email. */
export default function BudgetCard({ budget }: { budget: Budget }) {
  const used = budget.used ?? 0;
  const level = LEVELS[used >= 1 ? "over" : used >= 0.8 ? "near" : "ok"];
  const alert = budget.alert;

  return (
    <Card component="section" aria-labelledby="budget-heading" sx={{ height: "100%" }}>
      <CardContent>
        <Stack spacing={1.5}>
          <div>
            <Typography id="budget-heading" variant="h3">
              Monthly budget
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Real LLM spending in {monthName.format(parseBucket(budget.month))}. An alert is emailed to {budget.recipients} once
              spending passes {formatUsd(budget.threshold_usd)}.
            </Typography>
          </div>

          <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "baseline", flexWrap: "wrap" }}>
            <Typography component="span" sx={{ fontSize: 32, fontWeight: 600, lineHeight: 1.1 }}>
              {formatUsd(budget.spent_usd)}
            </Typography>
            <Typography component="span" variant="body2" color="text.secondary">
              of {formatUsd(budget.threshold_usd)}
            </Typography>
            <Chip size="small" variant="outlined" color={level.color} icon={level.icon} label={level.label} />
          </Stack>

          <LinearProgress
            variant="determinate"
            color={level.color}
            value={Math.min(100, used * 100)}
            aria-label="Monthly budget used"
            aria-valuetext={`${formatUsd(budget.spent_usd)} of ${formatUsd(budget.threshold_usd)} (${formatPercent(used)})`}
            sx={{ height: 10, borderRadius: 5 }}
          />
          <Typography variant="caption" color="text.secondary">
            {formatPercent(used)} of the monthly budget used
          </Typography>

          {alert ? (
            alert.delivered ? (
              <Alert severity="success">
                Alert emailed to {alert.recipients}
                {alert.attempted_at ? ` on ${sentAt.format(new Date(alert.attempted_at))}` : ""}.
              </Alert>
            ) : (
              <Alert severity="error">
                <strong>Spending passed the budget but the alert email was not delivered.</strong> {alert.error ?? ""} It is
                retried every hour.
              </Alert>
            )
          ) : (
            !budget.email_configured && (
              <Alert severity="warning">
                Email alerts are not set up yet: add the <code>AWN_SMTP_*</code> settings on the server so the budget alert can be
                sent.
              </Alert>
            )
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
