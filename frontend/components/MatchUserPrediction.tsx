"use client";

import { UserPredictionCard } from "@/components/UserPredictionCard";
import { useMatchPicks } from "@/lib/useMatchPicks";
import { useTimezone } from "@/lib/useTimezone";
import type { MatchSummary } from "@/lib/types";

/** Client wrapper that wires the anonymous, locally-stored match pick into the
 *  match-detail "Your prediction" section. Orients the card around the home
 *  team (the detail page has no single followed country). */
export function MatchUserPrediction({ match }: { match: MatchSummary }) {
  const { picks, setPick } = useMatchPicks();
  const { tz } = useTimezone();

  return (
    <UserPredictionCard
      match={match}
      country={match.teams.home}
      pick={picks[match.match_id]}
      onPick={(p) => setPick(match.match_id, p)}
      tz={tz}
    />
  );
}
