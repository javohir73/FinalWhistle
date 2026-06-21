/** How did the model's call compare with the real result?
 *  Only meaningful for finished matches with a known score. */
import type { MatchSummary, Probabilities } from "./types";
import { topOutcome, type Outcome } from "./format";

export type Verdict = {
  kind: "exact" | "winner" | "miss";
  label: string;
};

export type Call = { label: string; tone: "win" | "draw" };

/** The model's group-stage call for a fixture as a home/draw/away pick — the
 *  argmax of the pre-match probabilities, falling back to the named
 *  predicted_winner when probabilities are missing. Null when the model has no
 *  usable call. Used to prefill the My Bracket group stage from AI predictions. */
export function predictedOutcome(m: MatchSummary): Outcome | null {
  if (m.probabilities) return topOutcome(m.probabilities);
  if (m.predicted_winner && m.predicted_winner === m.teams.home) return "home";
  if (m.predicted_winner && m.predicted_winner === m.teams.away) return "away";
  return null;
}

/** Plain-language pre-match read of a prediction — the friendly one-liner that
 *  sits with the raw probabilities. "{Team} favoured" when a side clears 55%,
 *  "Too close to call" when the draw leads or the sides are within 6%, otherwise
 *  "{Team} edge it" for a slim lean. */
export function prematchCall(
  probabilities: Probabilities | null | undefined,
  teams: { home: string; away: string },
): Call | null {
  if (!probabilities) return null;
  const { home_win: h, draw: d, away_win: a } = probabilities;
  if ((d >= h && d >= a) || Math.abs(h - a) <= 0.06) {
    return { label: "Too close to call", tone: "draw" };
  }
  const leader = h >= a ? teams.home : teams.away;
  const lead = Math.max(h, a);
  return { label: lead > 0.55 ? `${leader} favoured` : `${leader} edge it`, tone: "win" };
}

export function predictionVerdict(m: MatchSummary): Verdict | null {
  if (m.status !== "finished" || m.score_home == null || m.score_away == null) {
    return null;
  }
  const ps = m.predicted_score;
  if (ps && ps.home != null && ps.away != null && ps.home === m.score_home && ps.away === m.score_away) {
    return { kind: "exact", label: "Exact score predicted" };
  }
  const actual =
    m.score_home > m.score_away ? "home" : m.score_home < m.score_away ? "away" : "draw";
  if (m.probabilities && topOutcome(m.probabilities) === actual) {
    return { kind: "winner", label: "Result predicted right" };
  }
  return { kind: "miss", label: "Model missed this one" };
}
