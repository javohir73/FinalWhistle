import type { MatchSummary } from "./types";

/** Upper bound on how long after kickoff a match can still plausibly be "in
 *  play": 90' + half-time + full extra time + a penalty shootout + stoppage,
 *  with margin — no real match runs this long. */
export const MAX_LIVE_MINUTES = 180;

/** True only when the feed says a match is in play AND it kicked off recently
 *  enough to still be playing. The status field alone is not enough: if the live
 *  refresh stalls (cron down, provider lag, no API key), a finished match stays
 *  `in_play` forever and the UI shows "LIVE 90'" hours after full time. Bounding
 *  by kickoff makes the live state self-heal even when the feed doesn't. */
export function isLiveNow(
  m: Pick<MatchSummary, "status" | "kickoff_utc">,
  now: Date = new Date(),
): boolean {
  if (m.status !== "in_play") return false;
  if (!m.kickoff_utc) return true; // no kickoff to bound by — trust the feed
  const elapsedMin = (now.getTime() - new Date(m.kickoff_utc).getTime()) / 60_000;
  return elapsedMin <= MAX_LIVE_MINUTES;
}

/** True when any of `matches` belongs to `groupName` and is live right now.
 *  Used to flag group cards that have a match in progress. Reuses isLiveNow so
 *  the group-level signal stays consistent with the per-match live badge. */
export function groupHasLiveMatch(
  groupName: string,
  matches: Pick<MatchSummary, "group" | "status" | "kickoff_utc">[] | undefined,
  now: Date = new Date(),
): boolean {
  return (matches ?? []).some((m) => m.group === groupName && isLiveNow(m, now));
}

/** Short scoreboard label for a match's live state. The pulsing dot beside it
 *  carries the "live" meaning, so the text is just the clock or phase:
 *
 *    57'  ·  45+2'  ·  HT  ·  ET 105'  ·  PENS  ·  FT
 *
 *  Returns "" before kickoff. The free feed has no live minute, so open-play
 *  shows an estimate (and "LIVE" if even that is unavailable); half-time,
 *  extra time and penalties come from the period and read exactly. */
export function liveLabel(
  s: Pick<MatchSummary, "status" | "minute" | "period" | "injury_time">,
): string {
  if (s.status === "finished") return "FT";
  if (s.status !== "in_play") return "";

  switch (s.period) {
    case "penalty_shootout":
      return "PENS";
    case "half_time":
      return "HT";
    case "extra_time":
      // Real ET minute (paid feed) shows "ET 105'"; the free-tier estimate caps
      // at 90, so we show a bare "ET" rather than a wrong number.
      return s.minute != null && s.minute > 90 ? `ET ${s.minute}'` : "ET";
    default: {
      const m = s.minute;
      if (m == null) return "LIVE";
      // football-data reports stoppage as minute 45/90 plus injuryTime.
      if (s.injury_time && (m === 45 || m === 90)) return `${m}+${s.injury_time}'`;
      return `${m}'`;
    }
  }
}

/** The shootout tally as "5–4", or null when not a penalty shootout. */
export function penaltyTally(
  s: Pick<MatchSummary, "penalty_home" | "penalty_away">,
): string | null {
  if (s.penalty_home == null || s.penalty_away == null) return null;
  return `${s.penalty_home}–${s.penalty_away}`;
}
