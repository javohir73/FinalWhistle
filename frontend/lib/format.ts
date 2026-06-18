/** Small presentation helpers shared across the UI. */
import type { Probabilities } from "./types";

export function pct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export type Outcome = "home" | "draw" | "away";

export function topOutcome(p: Probabilities): Outcome {
  const entries: [Outcome, number][] = [
    ["home", p.home_win],
    ["draw", p.draw],
    ["away", p.away_win],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0][0];
}

export function formatScore(home: number | null, away: number | null): string {
  if (home == null || away == null) return "—";
  return `${home}–${away}`;
}
