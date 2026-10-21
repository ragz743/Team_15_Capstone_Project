import { useId, useState } from "react";
import { formatCount, formatUsd } from "../format";
import { projectMonth, type ScaleBasis } from "../projection";

type ScaleProjectionProps = { basis: ScaleBasis | null; currentUsers: number };

// slider positions map to users on a log scale so 100 and 100,000 are both easy to reach
const MIN_USERS = 10;
const MAX_USERS = 100_000;
const toSlider = (users: number) => Math.log10(Math.min(MAX_USERS, Math.max(MIN_USERS, users)));
const fromSlider = (position: number) => {
  const users = 10 ** position;
  const magnitude = 10 ** Math.max(0, Math.floor(Math.log10(users)) - 1);
  return Math.round(users / magnitude) * magnitude;
};

/** "What would it cost at N monthly users?" based on observed per user cost. */
export default function ScaleProjection({ basis, currentUsers }: ScaleProjectionProps) {
  const [users, setUsers] = useState(() => Math.max(1_000, currentUsers * 10));
  const inputId = useId();

  if (!basis) {
    return (
      <section className="card projection">
        <h3>Cost at scale</h3>
        <p className="chart-empty">A projection needs at least one month with identified users.</p>
      </section>
    );
  }

  const projected = projectMonth(basis, users);
  const basisLabel = basis.usesPartialMonth
    ? "the current month to date"
    : `${basis.months} complete month${basis.months === 1 ? "" : "s"}`;

  return (
    <section className="card projection" aria-labelledby={`${inputId}-title`}>
      <h3 id={`${inputId}-title`}>Cost at scale</h3>
      <p className="card-subtitle">
        Projected monthly LLM cost from {formatUsd(basis.costPerUser)} and {basis.callsPerUser.toFixed(0)} LLM calls per
        monthly user, averaged over {basisLabel}.
      </p>

      <label htmlFor={inputId} className="projection-label">
        Monthly active users
      </label>
      <div className="projection-inputs">
        <input
          type="range"
          min={Math.log10(MIN_USERS)}
          max={Math.log10(MAX_USERS)}
          step={0.01}
          value={toSlider(users)}
          onChange={(event) => setUsers(fromSlider(Number(event.target.value)))}
          aria-label="Monthly active users"
          aria-valuetext={`${formatCount(users)} users`}
        />
        <input
          id={inputId}
          type="number"
          min={1}
          step={1}
          inputMode="numeric"
          value={users}
          onChange={(event) => setUsers(Math.max(1, Math.round(Number(event.target.value) || 1)))}
        />
      </div>

      <dl className="projection-results">
        <div>
          <dt>Monthly LLM cost</dt>
          <dd>{formatUsd(projected.cost)}</dd>
        </div>
        <div>
          <dt>Monthly LLM calls</dt>
          <dd>{formatCount(Math.round(projected.calls))}</dd>
        </div>
        <div>
          <dt>Yearly LLM cost</dt>
          <dd>{formatUsd(projected.cost * 12)}</dd>
        </div>
      </dl>
      <p className="stat-hint">Assumes usage per user stays the same as it grows and current model prices.</p>
    </section>
  );
}
