"use client";

import { useTimezone } from "@/lib/useTimezone";
import { MatchCard } from "@/components/MatchCard";
import type { MatchSummary } from "@/lib/types";

/** Client island: the group's fixtures as match cards in the user's timezone
 *  (kickoff time is client-only; the rest of the group page is server-rendered). */
export function GroupFixtureList({ matches }: { matches: MatchSummary[] }) {
  const { tz } = useTimezone();
  if (matches.length === 0) {
    return <p className="text-sm text-muted">Fixtures will appear once the draw is finalized.</p>;
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {matches.map((m) => (
        <MatchCard key={m.match_id} match={m} tz={tz} />
      ))}
    </div>
  );
}
