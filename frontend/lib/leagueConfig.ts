/** League config for the football "Beat the AI" loop (design doc:
 *  2026-07-24-league-score-predictions-design.md) -- the ONE place a league
 *  code/label lives on the frontend. Every component/lib function below this
 *  takes `league` as a prop/argument; nothing else should hardcode a league
 *  code. Mirrors the backend's own _LEAGUE_TOURNAMENT_NAMES config idiom
 *  (backend/app/api/league_score_predictions.py). */
export const DEFAULT_LEAGUE = "epl";

/** Display label per league code -- copy only, never used for API identity. */
const LEAGUE_LABELS: Record<string, string> = {
  epl: "Premier League",
  laliga: "La Liga",
  bundesliga: "Bundesliga",
  ucl: "UEFA Champions League",
};

export function leagueLabel(league: string): string {
  return LEAGUE_LABELS[league] ?? league.toUpperCase();
}

/** Active /tips leagues. UCL joins after real league-stage matchweeks load. */
export const ACTIVE_LEAGUES: string[] = ["epl", "laliga", "bundesliga"];
