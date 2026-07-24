"use client";

import { useState } from "react";
import { ClaimDeviceLeagueTips } from "@/components/leagueTips/ClaimDeviceLeagueTips";
import { LeagueTipsPicker } from "@/components/leagueTips/LeagueTipsPicker";
import { LeagueYouVsAi } from "@/components/leagueTips/LeagueYouVsAi";
import { LeagueTipsLeaderboard } from "@/components/leagueTips/LeagueTipsLeaderboard";

/** The league beat-the-AI loop's client half (design doc: League Score
 *  Predictions, 2026-07-24) -- league-generic port of components/nrl/
 *  NrlTipsPlaySection.tsx: predict, "you vs the AI", and the weekly/season
 *  leaderboard, all living under /tips. `league` flows down as a prop
 *  everywhere; Phase 1's one config entry ("epl") lives only in
 *  lib/leagueConfig.ts, one level up (app/tips/page.tsx), never in here.
 *
 *  The matchweek shown isn't known until LeagueTipsPicker's first load
 *  resolves it server-side (there is no public tipsheet endpoint to seed it
 *  from, unlike NRL) -- the leaderboard only mounts once that's known, so it
 *  never has to guess which matchweek "current" means. */
export function LeagueTipsPlaySection({ league }: { league: string }) {
  const [matchweek, setMatchweek] = useState<number | null>(null);
  return (
    <div className="mt-8 space-y-6">
      <ClaimDeviceLeagueTips />
      <LeagueTipsPicker league={league} onMatchweekChange={setMatchweek} />
      <LeagueYouVsAi league={league} />
      {matchweek != null && <LeagueTipsLeaderboard league={league} matchweek={matchweek} />}
    </div>
  );
}
