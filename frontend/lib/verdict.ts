/** How did the model's call compare with the real result?
 *  Only meaningful for finished matches with a known score. */
import type { MatchSummary } from "./types";
import { topOutcome } from "./format";

export type Verdict = {
  kind: "exact" | "winner" | "miss";
  label: string;
};

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
