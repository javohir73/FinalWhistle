"use client";

import Link from "next/link";
import { useTimezone } from "@/lib/useTimezone";
import { kickoffTime, tzAbbrev } from "@/lib/datetime";
import { Flag } from "@/components/Flag";
import { formatScore, pct } from "@/lib/format";
import type { MatchSummary } from "@/lib/types";

/** Client island: a team's fixtures in the user's timezone. The soonest match
 *  that hasn't finished is flagged "Next". Each row links to the match page. */
export function TeamFixtures({
  matches,
  teamName,
}: {
  matches: MatchSummary[];
  teamName: string;
}) {
  const { tz } = useTimezone();

  // Chronological; undated last.
  const sorted = [...matches].sort((a, b) => {
    if (!a.kickoff_utc) return 1;
    if (!b.kickoff_utc) return -1;
    return a.kickoff_utc < b.kickoff_utc ? -1 : 1;
  });
  const nextId = sorted.find((m) => m.status !== "finished")?.match_id ?? null;

  if (sorted.length === 0) {
    return <p className="text-sm text-muted">No fixtures scheduled yet.</p>;
  }

  const shortDate = (iso: string) =>
    new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      weekday: "short",
      day: "numeric",
      month: "short",
    }).format(new Date(iso));

  return (
    <ul className="divide-y divide-border/50">
      {sorted.map((m) => {
        const home = m.teams.home === teamName;
        const opponent = home ? m.teams.away : m.teams.home;
        const p = m.probabilities;
        const teamWin = p ? (home ? p.home_win : p.away_win) : null;
        const finished = m.status === "finished";
        return (
          <li key={m.match_id}>
            <Link
              href={`/match/${m.match_id}`}
              className="flex items-center gap-3 py-3 transition hover:text-win focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
            >
              <span className="w-20 shrink-0 text-xs text-muted">
                {m.kickoff_utc ? (
                  <>
                    <span className="block font-semibold text-foreground/90">{shortDate(m.kickoff_utc)}</span>
                    <span className="block">
                      {kickoffTime(m.kickoff_utc, tz)} {tzAbbrev(m.kickoff_utc, tz)}
                    </span>
                  </>
                ) : (
                  "TBC"
                )}
              </span>
              <span className="shrink-0 text-[11px] uppercase tracking-wide text-muted">
                {home ? "vs" : "@"}
              </span>
              <Flag team={opponent} size={20} />
              <span className="min-w-0 flex-1 truncate font-medium">{opponent}</span>
              {finished && m.score_home != null && m.score_away != null ? (
                <span className="shrink-0 font-display text-sm font-bold tabular-nums">
                  {home
                    ? formatScore(m.score_home, m.score_away)
                    : formatScore(m.score_away, m.score_home)}
                </span>
              ) : teamWin != null ? (
                <span className="shrink-0 text-xs font-semibold tabular-nums text-win">
                  {pct(teamWin)} win
                </span>
              ) : null}
              {m.match_id === nextId && !finished && (
                <span className="shrink-0 rounded-full bg-win/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-win ring-1 ring-win/30">
                  Next
                </span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
