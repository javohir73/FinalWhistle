import type { NrlMatch, NrlRound } from "./types";

/** NRL games run ~100 minutes wall-clock; 120 adds margin without stranding
 *  a "live" badge for hours when ingest lags. The list API only knows
 *  scheduled/finished, so liveness is derived purely from this kickoff
 *  window — self-healing, same rationale as liveLabel.MAX_LIVE_MINUTES. */
export const NRL_LIVE_WINDOW_MINUTES = 120;

export function isNrlLiveNow(
  m: Pick<NrlMatch, "status" | "kickoff_utc">,
  now: Date = new Date(),
): boolean {
  if (m.status === "finished" || !m.kickoff_utc) return false;
  const elapsedMin = (now.getTime() - new Date(m.kickoff_utc).getTime()) / 60_000;
  return elapsedMin >= 0 && elapsedMin <= NRL_LIVE_WINDOW_MINUTES;
}

export interface RoundGroup {
  round: number | null;
  matches: NrlMatch[];
}

const byKickoff = (dir: 1 | -1) => (a: NrlMatch, b: NrlMatch) =>
  dir * (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? "");

/** In-window matches across all rounds, kickoff asc, tagged with their round
 *  (SportMatchCard needs the round for its eyebrow and href). */
export function liveNow(
  rounds: NrlRound[],
  now: Date = new Date(),
): { round: number | null; match: NrlMatch }[] {
  return rounds
    .flatMap((r) => r.matches.filter((m) => isNrlLiveNow(m, now)).map((match) => ({ round: r.round, match })))
    .sort((a, b) => byKickoff(1)(a.match, b.match));
}

/** Scheduled and not in the live window — round asc, kickoff asc within. */
export function upcomingRounds(rounds: NrlRound[], now: Date = new Date()): RoundGroup[] {
  return rounds
    .map((r) => ({
      round: r.round,
      matches: r.matches
        .filter((m) => m.status === "scheduled" && !isNrlLiveNow(m, now))
        .sort(byKickoff(1)),
    }))
    .filter((g) => g.matches.length > 0)
    .sort((a, b) => (a.round ?? Infinity) - (b.round ?? Infinity));
}

/** Finished — round desc (latest results first), kickoff desc within. */
export function finishedRounds(rounds: NrlRound[]): RoundGroup[] {
  return rounds
    .map((r) => ({
      round: r.round,
      matches: r.matches.filter((m) => m.status === "finished").sort(byKickoff(-1)),
    }))
    .filter((g) => g.matches.length > 0)
    .sort((a, b) => (b.round ?? -Infinity) - (a.round ?? -Infinity));
}
