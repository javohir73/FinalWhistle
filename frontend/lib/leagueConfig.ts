/** League config for the football "Beat the AI" loop (design doc:
 *  2026-07-24-league-score-predictions-design.md) -- the ONE place a league
 *  code/label lives on the frontend. Every component/lib function below this
 *  takes `league` as a prop/argument; nothing else should hardcode a league
 *  code. Mirrors the backend's own _LEAGUE_TOURNAMENT_NAMES config idiom
 *  (backend/app/api/league_score_predictions.py). */
export const DEFAULT_LEAGUE = "epl";

/** Display label per league code -- copy only, never used for API identity
 *  (the API always takes the short code). La Liga/Bundesliga are registered
 *  here so share pages/OG cards for those leagues already label correctly
 *  (leagueLabel() is called there regardless of ACTIVE_LEAGUES), same as
 *  pipeline/leagues.py's LEAGUES dict registering both ahead of activation. */
const LEAGUE_LABELS: Record<string, string> = {
  epl: "Premier League",
  laliga: "La Liga",
  bundesliga: "Bundesliga",
};

export function leagueLabel(league: string): string {
  return LEAGUE_LABELS[league] ?? league.toUpperCase();
}

/** Which leagues the /tips switcher actually offers, in display order.
 *  Mirrors pipeline/leagues.py's ACTIVE_LEAGUES/PHASE_2_PENDING_ACTIVATION
 *  split: La Liga and Bundesliga are labeled above (so links to them already
 *  render right) but not yet active here -- activating a league on the
 *  switcher only makes sense once the pipeline has actually ingested its
 *  fixtures, so this stays EPL-only until that's live. A league switcher (see
 *  components/leagueTips/LeagueSwitcher.tsx) only renders once this list has
 *  more than one entry; EPL-only keeps today's /tips pixel-for-pixel
 *  identical. */
export const ACTIVE_LEAGUES: string[] = ["epl"];
