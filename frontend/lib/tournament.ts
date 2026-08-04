/** Server-side active-tournament lookup with a WC26 fallback (league pivot,
 *  see docs/LEAGUE-PIVOT-PLAN.md D5/D6). `GET /api/tournaments/active` ships
 *  with a parallel backend workstream, so every caller here must degrade
 *  gracefully until it does — this file is the one place that fallback lives. */
import { getActiveTournamentServer, getCompetitionTournamentServer } from "./api";
import { COMPETITIONS, isWiredFootballCompetition, type CompetitionId } from "./sports";
import type { ActiveTournament } from "./types";

export const WC26_FALLBACK: ActiveTournament = {
  id: 0,
  name: "World Cup 2026",
  year: 2026,
  format: "knockout",
  has_brackets: true,
};

/** Resolves the active tournament for copy (C8) and surface gating (C6). A
 *  404 (endpoint not deployed yet) or any network/parse error both fall back
 *  to WC26 rather than throwing, so this PR renders today's WC26 behavior
 *  exactly until the backend workstream ships. */
export async function getTournament(): Promise<ActiveTournament> {
  try {
    const tournament = await getActiveTournamentServer();
    return tournament ?? WC26_FALLBACK;
  } catch {
    return WC26_FALLBACK;
  }
}

/** Resolve metadata for one namespaced competition.
 *
 * A known competition can be navigable before its season feed is loaded. In
 * that case return registry-backed metadata with id=0 so the page can show an
 * empty state without falling back to whichever other tournament happens to
 * be active.
 */
export async function getCompetitionTournament(
  competition: CompetitionId,
): Promise<ActiveTournament> {
  try {
    const tournament = await getCompetitionTournamentServer(competition);
    if (tournament) return tournament;
  } catch {
    // The route surfaces a competition-specific empty state below.
  }
  const config = COMPETITIONS[competition];
  return {
    id: 0,
    name: config.label,
    year: 2026,
    format: config.format === "league" ? "league" : "knockout",
    has_brackets: config.hasBracket,
  };
}

/** Tournament naming for a surface that may or may not carry a competition in
 * its URL -- the OG image convention files, which one component serves for
 * both `/match/:id` and `/football/:comp/match/:id`.
 *
 * The namespaced routes MUST name their own competition. getTournament()
 * answers "which tournament is active right now", and once the Champions
 * League was activated that made it the answer for every competition: a
 * World Cup share card came back captioned "UEFA Champions League 2026-27".
 * A legacy route has no comp segment and keeps the active-tournament copy it
 * has always had.
 */
export function getTournamentForRoute(comp?: string): Promise<ActiveTournament> {
  return comp !== undefined && isWiredFootballCompetition(comp)
    ? getCompetitionTournament(comp)
    : getTournament();
}
