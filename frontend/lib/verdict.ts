/** How did the model's call compare with the real result?
 *  Only meaningful for finished matches with a known score. */
import type { MatchSummary, Probabilities } from "./types";
import { topOutcome, type Outcome } from "./format";

export type Verdict = {
  kind: "exact" | "winner" | "miss";
  label: string;
  /** The model predicts regulation (90-min) goals only — no extra time or
   *  penalties. For knockout matches this is "90 min" so the UI can qualify the
   *  call; null for group games, where the result IS the 90-min result. */
  basis: "90 min" | null;
  /** Set when a knockout match was level after 90 and decided on penalties. The
   *  shootout isn't modelled, so the UI flags who actually advanced. */
  shootout: { winner: string; text: string } | null;
};

/** A finished match is "knockout" when it's past the group stage. The model is
 *  regulation-only, so only knockout results can diverge from the 90-min call
 *  (extra time / penalties), which is what the basis + shootout note explain. */
function isKnockout(stage: string): boolean {
  return stage.toLowerCase() !== "group";
}

/** A penalty shootout result, or null when the match wasn't decided on pens.
 *  Both penalty tallies present means a shootout took place. */
function shootoutOf(m: MatchSummary): { winner: string; text: string } | null {
  if (m.penalty_home == null || m.penalty_away == null) return null;
  const homeWon = m.penalty_home > m.penalty_away;
  const winner = homeWon ? m.teams.home : m.teams.away;
  const hi = Math.max(m.penalty_home, m.penalty_away);
  const lo = Math.min(m.penalty_home, m.penalty_away);
  return { winner, text: `${winner} won ${hi}–${lo} on penalties` };
}

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
  // The model's call is always for regulation. Knockout matches can diverge from
  // it via extra time / penalties, so carry the 90-min basis and any shootout.
  const basis: "90 min" | null = isKnockout(m.stage) ? "90 min" : null;
  const shootout = shootoutOf(m);
  const ps = m.predicted_score;
  // Scoreline verdict on the 90-minute basis when captured (matches the model
  // record's exact_score_correct); the final score is the fallback basis.
  const exactHome = m.score_home_90 ?? m.score_home;
  const exactAway = m.score_away_90 ?? m.score_away;
  if (ps && ps.home != null && ps.away != null && ps.home === exactHome && ps.away === exactAway) {
    return { kind: "exact", label: "Exact score predicted", basis, shootout };
  }
  const actual =
    m.score_home > m.score_away ? "home" : m.score_home < m.score_away ? "away" : "draw";
  if (m.probabilities && topOutcome(m.probabilities) === actual) {
    return { kind: "winner", label: "Result predicted right", basis, shootout };
  }
  return { kind: "miss", label: "Model missed this one", basis, shootout };
}
