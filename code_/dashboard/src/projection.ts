import type { MonthPoint } from "./types.ts";

export type ScaleBasis = {
  /** LLM cost per monthly active user, from identified users only. */
  costPerUser: number;
  /** LLM calls per monthly active user. */
  callsPerUser: number;
  /** Months the averages are based on. */
  months: number;
  /** True when no complete month exists yet and the current month to date was used. */
  usesPartialMonth: boolean;
};

/**
 * Per user monthly cost and call volume, averaged over complete months.
 * Falls back to the current partial month when there is no complete month with users.
 */
export function scaleBasis(months: MonthPoint[]): ScaleBasis | null {
  const complete = months.filter((m) => !m.partial && m.users > 0);
  const basis = complete.length > 0 ? complete : months.filter((m) => m.users > 0);
  if (basis.length === 0) return null;

  const users = basis.reduce((total, m) => total + m.users, 0);
  const cost = basis.reduce((total, m) => total + (m.avg_cost_per_user ?? 0) * m.users, 0);
  const calls = basis.reduce((total, m) => total + m.llm_calls, 0);
  return {
    costPerUser: cost / users,
    callsPerUser: calls / users,
    months: basis.length,
    usesPartialMonth: complete.length === 0,
  };
}

/** Projected monthly LLM cost and calls at a given number of monthly active users. */
export function projectMonth(basis: ScaleBasis, monthlyUsers: number): { cost: number; calls: number } {
  return { cost: basis.costPerUser * monthlyUsers, calls: basis.callsPerUser * monthlyUsers };
}
