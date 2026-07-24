/** Phase 1 league config for the football "Beat the AI" loop (design doc:
 *  2026-07-24-league-score-predictions-design.md) -- the ONE place the "epl"
 *  literal lives on the frontend. Every component/lib function below this
 *  takes `league` as a prop/argument; nothing else should hardcode a league
 *  code. Mirrors the backend's own _LEAGUE_TOURNAMENT_NAMES config idiom
 *  (backend/app/api/league_score_predictions.py). Phase 2 (La Liga,
 *  Bundesliga) adds entries here and a league switcher UI -- no other
 *  frontend file should need to change. */
export const DEFAULT_LEAGUE = "epl";

/** Display label per league code -- copy only, never used for API identity
 *  (the API always takes the short code). */
const LEAGUE_LABELS: Record<string, string> = {
  epl: "Premier League",
};

export function leagueLabel(league: string): string {
  return LEAGUE_LABELS[league] ?? league.toUpperCase();
}
