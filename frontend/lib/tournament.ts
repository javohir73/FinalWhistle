/** Server-side active-tournament lookup with a WC26 fallback (league pivot,
 *  see docs/LEAGUE-PIVOT-PLAN.md D5/D6). `GET /api/tournaments/active` ships
 *  with a parallel backend workstream, so every caller here must degrade
 *  gracefully until it does — this file is the one place that fallback lives. */
import { getActiveTournamentServer } from "./api";
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
