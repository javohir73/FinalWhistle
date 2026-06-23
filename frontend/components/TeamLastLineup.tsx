"use client";

import { useTimezone } from "@/lib/useTimezone";
import { kickoffDate } from "@/lib/datetime";
import { MatchLineups } from "@/components/MatchLineups";

/** Team-dashboard "Last XI": renders the team's most-recent finished match's
 *  lineup (filtered to this team's side) via the shared MatchLineups path,
 *  labelled "Last XI · vs {opponent} · {date}". The match selection happens on
 *  the server; this island only formats the date in the user's timezone and
 *  delegates the fetch/degradation to MatchLineups. */
export function TeamLastLineup({
  matchId,
  side,
  opponent,
  kickoffUtc,
}: {
  matchId: number;
  side: "home" | "away";
  opponent: string;
  kickoffUtc: string | null;
}) {
  const { tz } = useTimezone();
  const date = kickoffUtc ? kickoffDate(kickoffUtc, tz) : null;
  const label = ["Last XI", `vs ${opponent}`, date].filter(Boolean).join(" · ");

  return (
    <section>
      <h2 className="mb-3 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </h2>
      <MatchLineups matchId={matchId} side={side} />
    </section>
  );
}
