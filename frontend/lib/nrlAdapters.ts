/** Pure mappers from the /api/nrl/* shapes onto the shared Floodlight component
 *  props (MatchCard's MatchSummary, StandingsTable's row). No React, SSR-safe,
 *  so server and client NRL surfaces share one translation. NRL semantics stay
 *  intact: a 3-way probability bar with a naturally-small draw (never zeroed),
 *  margin chips, and the (season, round, match_no) match href. Live minute/
 *  period is deliberately not modelled here -- the list API only knows
 *  scheduled/finished, so liveness lives in nrlLive/MatchesClient and the
 *  match-centre is P4. */

import type { LadderRow, MatchSummary, NrlMatch } from "./types";
import type { StandingsTableRow } from "@/components/StandingsTable";

/** The favoured side's name, or null when there's no prediction, the pick is a
 *  dead heat, or the team is still TBC -- an honest null beats a false
 *  favourite. Draws aren't "winners", so only p_home vs p_away decides it. */
function favouredSide(m: NrlMatch): string | null {
  const p = m.prediction;
  if (!p) return null;
  if (p.p_home > p.p_away) return m.home ?? null;
  if (p.p_away > p.p_home) return m.away ?? null;
  return null;
}

/** NrlMatch -> MatchSummary for the shared MatchCard. status collapses to
 *  finished-vs-scheduled (SportMatchCard's only distinction); the live-only,
 *  football-shaped fields (minute/period/penalties/goal_events) stay empty.
 *  probabilities keep all three outcomes so the W/D/L bar renders the small
 *  draw segment; predicted_score/confidence are null (NrlPrediction has
 *  neither), venue city/country too (the list payload carries no locale). */
export function nrlMatchToSummary(m: NrlMatch): MatchSummary {
  const p = m.prediction;
  return {
    match_id: m.id,
    stage: "",
    group: null,
    kickoff_utc: m.kickoff_utc,
    venue: m.venue,
    venue_city: null,
    venue_country: null,
    is_neutral: false,
    status: m.status === "finished" ? "finished" : "scheduled",
    score_home: m.score_home,
    score_away: m.score_away,
    minute: null,
    period: null,
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    goal_events: [],
    teams: { home: m.home ?? "TBC", away: m.away ?? "TBC" },
    predicted_winner: favouredSide(m),
    probabilities: p
      ? { home_win: p.p_home, draw: p.p_draw, away_win: p.p_away }
      : null,
    predicted_score: null,
    confidence: null,
    live_probabilities: undefined,
  };
}

/** The match-detail URL, which needs the full (season, round, match_no) triple.
 *  A fixture whose season or round is still TBC has no detail page -> null, so
 *  callers render a plain (unlinked) card. Mirrors SportMatchCard's link guard
 *  exactly. */
export function nrlMatchHref(
  season: number | null | undefined,
  round: number | null | undefined,
  matchNo: number,
): string | null {
  return season != null && round != null
    ? `/nrl/match/${season}/${round}/${matchNo}`
    : null;
}

/** The model's expected winning margin, or null when unpredicted -- drives the
 *  margin chip. */
export function nrlExpectedMargin(m: NrlMatch): number | null {
  return m.prediction?.expected_margin ?? null;
}

/** LadderRow[] -> StandingsTable superset rows. NRL points/diff feed the shared
 *  projected_* columns; the native played/wins/draws/losses/points/diff ride
 *  alongside for the W-L / Diff / Pts columns. projection_pct is the per-team
 *  top-8 finals chance (null when we have no projection). Rows arrive pre-sorted
 *  by rank, so StandingsTable's index+1 === rank drives the finals zone tint. */
export function ladderRowsToStandings(
  rows: LadderRow[],
  projectionsByTeam?: Record<string, { top8: number; top4: number }>,
): StandingsTableRow[] {
  return rows.map((r) => ({
    team_id: r.team_id,
    team: r.name,
    projected_points: r.points,
    projected_goal_diff: r.diff,
    projected_goals_for: 0,
    qualification_prob: null,
    played: r.played,
    wins: r.wins,
    draws: r.draws,
    losses: r.losses,
    points: r.points,
    diff: r.diff,
    projection_pct: projectionsByTeam?.[r.name]?.top8 ?? null,
  }));
}
