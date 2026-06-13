import type { MatchSummary } from "./types";

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
