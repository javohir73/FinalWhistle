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

/** expected_margin is home-minus-away points; read it out as the favoured
 *  side ("Sharks by 4.0") instead of a signed number whose convention the
 *  reader has to know. Shared by the NRL match hero and the fixture-card
 *  margin chip. */
export function expectedMarginLabel(margin: number, home: string, away: string): string {
  if (margin === 0) return "dead level";
  return `${margin > 0 ? home : away} by ${Math.abs(margin).toFixed(1)}`;
}
