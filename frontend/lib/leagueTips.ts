/** Client for the league "Beat the AI's scoreline" loop (design doc:
 *  2026-07-24-league-score-predictions-design.md): device_id-keyed scoreline
 *  submission, "you vs the AI" summary, and weekly/season leaderboards
 *  (backend/app/api/league_score_predictions.py). Mirrors lib/nrlTips.ts's
 *  shape, with `league` (a short code, e.g. "epl") replacing that file's
 *  implicit NRL scope and `matchweek` replacing `round`. Reuses session.ts's
 *  `request` for the same cold-start timeout / ApiError normalization as the
 *  rest of the app. */
import { request } from "./session";
import type {
  LeagueSeasonLeaderboardResponse,
  LeagueTipsLeaderboardResponse,
  LeagueTipsMineResponse,
  LeagueTipsShareResponse,
  LeagueTipsSummaryResponse,
  LeagueTipSubmitResponse,
  NrlTipClaimResponse,
} from "./types";

export const submitLeagueTip = (
  league: string,
  body: { device_id: string; match_id: number; predicted_home: number; predicted_away: number },
) =>
  request<LeagueTipSubmitResponse>(`/api/leagues/${league}/tips/submit`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/** matchweek omitted resolves to the current matchweek server-side (earliest
 *  still-scheduled, else latest played) -- callers pass it explicitly once
 *  they know it, so matchweek nav never disagrees with what was last shown. */
export const getMyLeagueTips = (league: string, device_id: string, matchweek?: number) =>
  request<LeagueTipsMineResponse>(
    `/api/leagues/${league}/tips/mine?${new URLSearchParams({
      device_id,
      ...(matchweek != null ? { matchweek: String(matchweek) } : {}),
    })}`,
  );

export const getLeagueTipsSummary = (league: string, device_id: string) =>
  request<LeagueTipsSummaryResponse>(
    `/api/leagues/${league}/tips/summary?device_id=${encodeURIComponent(device_id)}`,
  );

export const getLeagueTipsLeaderboard = (league: string, matchweek: number) =>
  request<LeagueTipsLeaderboardResponse>(
    `/api/leagues/${league}/tips/leaderboard?matchweek=${matchweek}`,
  );

/** Season-long leaderboard -- same below-gate reveal rule as the weekly
 *  board, just totaled across every graded matchweek instead of one. */
export const getLeagueSeasonLeaderboard = (league: string) =>
  request<LeagueSeasonLeaderboardResponse>(`/api/leagues/${league}/tips/leaderboard/season`);

/** Merge-on-signup ride-along: POST /api/nrl/tips/claim already claims a
 *  device's LeagueScorePrediction rows too (see that endpoint's own
 *  docstring) -- there is no separate league claim endpoint. This points at
 *  the same one lib/nrlTips.ts calls, named for this vertical the way this
 *  file mirrors the rest of nrlTips.ts's shape (each vertical keeps its own
 *  copy of the shared tip_players idiom rather than cross-importing --
 *  matches backend/app/api/league_score_predictions.py's own docstring). */
export const claimLeagueTips = (device_id: string) =>
  request<NrlTipClaimResponse>("/api/nrl/tips/claim", {
    method: "POST",
    body: JSON.stringify({ device_id }),
  });
