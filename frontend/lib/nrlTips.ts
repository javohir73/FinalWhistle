/** Client for the beat-the-AI loop (design doc: NRL Round Tips, Slice 2):
 *  device_id-keyed tip submission, "you vs the AI" summary, and the weekly
 *  leaderboard (backend/app/api/nrl_user_tips.py). Anonymous by default --
 *  device_id is NOT auth, mirrors session.ts's getOrCreateDeviceId/
 *  pingDailyActivity convention. Reuses session.ts's `request` so every call
 *  gets the same cold-start timeout and {error:{code,message}} -> ApiError
 *  normalization as the rest of the app. */
import { request } from "./session";
import type {
  NrlMyTipsResponse,
  NrlTipClaimResponse,
  NrlTipsLeaderboardResponse,
  NrlTipSubmitResponse,
  NrlTipsSummaryResponse,
} from "./types";

export const submitNrlTip = (body: {
  device_id: string;
  match_id: number;
  pick: "home" | "draw" | "away";
  margin?: number | null;
}) =>
  request<NrlTipSubmitResponse>("/api/nrl/tips/submit", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** season/round default to the current round server-side, same as
 *  getNrlTipsheetServer -- callers pass both explicitly so this can never
 *  disagree with the tipsheet round already on the page. */
export const getMyNrlTips = (device_id: string, season: number, round: number) =>
  request<NrlMyTipsResponse>(
    `/api/nrl/tips/mine?${new URLSearchParams({
      device_id,
      season: String(season),
      round: String(round),
    })}`,
  );

export const getNrlTipsSummary = (device_id: string) =>
  request<NrlTipsSummaryResponse>(`/api/nrl/tips/summary?device_id=${encodeURIComponent(device_id)}`);

export const getNrlTipsLeaderboard = (season: number, round: number) =>
  request<NrlTipsLeaderboardResponse>(`/api/nrl/tips/leaderboard?season=${season}&round=${round}`);

/** Merge-on-signup: idempotent server-side, safe to call on every sign-in. */
export const claimNrlTips = (device_id: string) =>
  request<NrlTipClaimResponse>("/api/nrl/tips/claim", {
    method: "POST",
    body: JSON.stringify({ device_id }),
  });
